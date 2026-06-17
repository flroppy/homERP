# vim: set foldlevel=0:
# vim: set foldmethod=indent:
# main.py
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Dict, Any
import os
import yaml
import uuid
import base64
import markdown
import shutil
import re
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pathlib import Path
from typing import List, Optional
from pylibdmtx.pylibdmtx import encode
from fuzzywuzzy import fuzz
from fuzzywuzzy import process
from brother_ql.labels import ALL_LABELS, Color
from brother_ql import BrotherQLRaster, create_label
from brother_ql.backends import guess_backend, backend_factory
from contextlib import asynccontextmanager
from config import settings
import git_backup

@asynccontextmanager
async def lifespan(app):
    git_backup.ensure_repo(HOUSE_ROOT)
    yield

# Initialize FastAPI app
app = FastAPI(title="House Inventory App", lifespan=lifespan)

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates directory
templates = Jinja2Templates(directory="templates")

# Root directory for house items
HOUSE_ROOT = Path(settings.data_dir)

# Ensure house directory exists
HOUSE_ROOT.mkdir(exist_ok=True)

# Attachments that are rendered rather than attachments
IGNORED_ATTACHMENTS = ['index.md', 'photo.jpg', 'thumbnail.jpg']

UUID_LENGTH = 8

REPO_PATH = HOUSE_ROOT

# Lazy printer backend — resolved on first print so the app starts without a printer
_printer_backend_class = None
_label_spec = None


def get_printer_backend():
    global _printer_backend_class, _label_spec
    if _printer_backend_class is None:
        selected = guess_backend(settings.barcode_printer_address)
        _printer_backend_class = backend_factory(selected)['backend_class']
        _label_spec = next(
            x for x in ALL_LABELS if x.identifier == settings.barcode_printer_tape
        )
    return _printer_backend_class, _label_spec

# Helper function to generate a 6-character base64 ID


def generate_id():
    # Generate a random UUID
    random_id = uuid.uuid4().bytes
    # Encode it to base64 and take the first 6 characters
    base64_id = base64.urlsafe_b64encode(
        random_id).decode('utf-8')[:UUID_LENGTH]
    return base64_id


def generate_barcode(item_id):
    encoded = encode(item_id.encode('utf8'))
    barcode_img = Image.frombytes(
        'RGB', (encoded.width, encoded.height), encoded.pixels)
    # Calculate the scaling factor based on the desired height
    barcode_height = barcode_img.height
    scale_factor = settings.barcode_rendered_height / barcode_height

    # Scale the barcode to the desired height while maintaining the aspect ratio
    barcode_width = int(barcode_img.width * scale_factor)
    barcode_img = barcode_img.resize(
        (barcode_width, settings.barcode_rendered_height), resample=Image.Resampling.NEAREST)

    return barcode_img


def shift_headings_down(markdown_text):
    # Function to shift headings down by one level
    def shift_heading(heading):
        # Match headings like # Heading, ## Heading, etc.
        match = re.match(r'^(#{1,6})\s+(.*)', heading)
        if match:
            # Count of '#' determines the heading level
            current_level = len(match.group(1))
            # Shift heading up, but not above level 6
            new_level = min(6, current_level + 1)
            # Create new heading with shifted level
            return '#' * new_level + ' ' + match.group(2)
        return heading  # Return as is if it's not a heading

    # Split text into lines and shift headings
    lines = markdown_text.splitlines()
    shifted_lines = [shift_heading(line) for line in lines]
    return '\n'.join(shifted_lines)


def adjust_paths_in_markdown(md_content, base_dir):
    # Regular expression to match links and images in Markdown
    import re
    url_pattern = r'(!?\[.*?\]\((.*?)\))'

    # Function to adjust the path for links/images
    def adjust_path(match):
        markdown_element = match.group(0)
        path = match.group(2)

        # Check if the path is relative
        if not path.startswith('http') and not path.startswith('#'):
            # Construct the full path based on base_dir
            absolute_path = os.path.join(base_dir, path)
            # Return the new element with the adjusted path
            return markdown_element.replace(path, absolute_path)
        return markdown_element

    # Adjust all links and images using regex substitution
    adjusted_md = re.sub(url_pattern, adjust_path, md_content)
    return adjusted_md

# Helper function to read index.md file


def read_index_file(item_path):
    index_path = item_path / "index.md"
    if not index_path.exists():
        return None
        # return {"name": item_path.name, "id": ""}

    with open(index_path, "r") as f:
        content = f.read()

    # Check if there's a YAML front matter
    if content.startswith("---"):
        # Extract YAML front matter
        _, yaml_text, markdown_text = content.split("---", 2)
        metadata = yaml.safe_load(yaml_text)
        markdown_text = markdown_text.strip()
    else:
        metadata = {"name": item_path.name, "id": ""}
        markdown_text = content

    photo_path = None
    if os.path.isfile(item_path / 'photo.png'):
        photo_path = Path('/download/') / \
            Path(*list(item_path.parts[1:])) / 'photo.png'
    elif os.path.isfile(item_path / 'photo.jpg'):
        photo_path = Path('/download/') / \
            Path(*list(item_path.parts[1:])) / 'photo.jpg'

    return {
        **metadata,
        "name": item_path.name,
        "path": item_path.relative_to(HOUSE_ROOT),
        "content": markdown_text,
        "html_content": render_html(markdown_text, Path(*list(item_path.parts[1:]))),
        "photo_path": photo_path
    }

# Adjust markdown for rendering


def render_html(markdown_text, item_path):
    markdown_text = adjust_paths_in_markdown(
        markdown_text, '/download/' / item_path)
    markdown_text = shift_headings_down(markdown_text)
    return markdown.markdown(markdown_text)

# Helper function to list items in a directory


def list_directory_items(directory_path):
    items = []
    attachments = []

    if not directory_path.exists():
        return items, attachments

    for path in directory_path.iterdir():
        if path.is_dir() and path.name != ".git":
            items.append(read_index_file(path))
        elif path.is_file() and path.name not in IGNORED_ATTACHMENTS:
            # This is an attachment
            attachments.append({
                "name": path.name,
                "owner": os.path.basename(os.path.dirname(path)),
                "path": path.relative_to(HOUSE_ROOT),
                "parent_path": Path(os.path.dirname(path)).relative_to(HOUSE_ROOT),
                "size": path.stat().st_size
            })

    # Sort items by name
    items.sort(key=lambda x: x["name"].lower())
    attachments.sort(key=lambda x: x["name"].lower())

    return items, attachments


def list_all_items(directory_path):
    items = []
    attachments = []

    # Get items and attachments in the current directory
    current_items, current_attachments = list_directory_items(directory_path)
    items.extend(current_items)
    attachments.extend(current_attachments)

    # Recursively process subdirectories
    for path in directory_path.iterdir():
        if path.is_dir() and path.name != ".git":  # Ignore .git directories
            items_recursive, attachments_recursive = list_all_items(path)
            items.extend(items_recursive)
            attachments.extend(attachments_recursive)

    return items, attachments

# Routes


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/all-items/")


@app.get("/browse/{path:path}", response_class=HTMLResponse)
async def browse(request: Request, path: str = ""):
    item_path = HOUSE_ROOT / path

    # Check if the path exists
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")

    # Get item metadata
    metadata = read_index_file(item_path)

    # Get sub-items and attachments
    items, attachments = list_directory_items(item_path)

    siblings = None
    if item_path != HOUSE_ROOT:
        siblings, unused = list_directory_items(
            Path(os.path.dirname(item_path)))
        siblings = [s for s in siblings if s.get(
            'name') != metadata.get('name')]
        siblings = sorted(siblings, key=lambda x: x['name'])

    # Sort sub-items
    items = sorted(items, key=lambda x: x['name'])

    # Get breadcrumbs
    breadcrumbs = []
    current_path = Path("")
    breadcrumbs.append({"name": "House", "path": ""})

    for part in Path(path).parts:
        current_path = current_path / part
        part_path = HOUSE_ROOT / current_path
        breadcrumbs.append({
            "name": part,
            "path": str(current_path)
        })

    return templates.TemplateResponse(
        request,
        "item.html",
        {
            "path": path,
            "metadata": metadata,
            "items": items,
            "siblings": siblings,
            "attachments": attachments,
            "breadcrumbs": breadcrumbs
        }
    )


@app.get("/all-items", response_class=HTMLResponse)
async def all_items(request: Request):

    def build_item_hierarchy(directory_path, total=0):
        items = []

        if not directory_path.exists():
            return items,total

        # TODO: Make this a helper function
        for path in directory_path.iterdir():
            if path.is_dir() and path.name != ".git":
                # This is a directory, add it and recursively fetch sub-items
                try:
                    metadata = read_index_file(path)
                    total+=1
                    sub_items,total=build_item_hierarchy(path,total)
                    items.append({
                        "path": path.relative_to(HOUSE_ROOT),
                        "name": metadata.get("name", path.name),
                        "id": metadata.get("id", ""),
                        "photo_path": metadata.get("photo_path", ""),
                        # Recursively get sub-items
                        "sub_items": sub_items
                    })
                except Exception:
                    # If we can't read the metadata, still list the directory
                    total+=1
                    sub_items,total=build_item_hierarchy(path,total)
                    items.append({
                        "path": path.relative_to(HOUSE_ROOT),
                        "name": path.name,
                        "id": "",
                        # Recursively get sub-items
                        "sub_items": sub_items
                    })
            # elif path.is_file() and path.name not in ["index.md", "barcode.png"]:
            #    # This is a file (attachment), we can optionally list them too
            #    items.append({
            #        "name": path.name,
            #        "path": path.relative_to(HOUSE_ROOT),
            #        "size": path.stat().st_size,
            #        "sub_items": []  # No sub-items for files
            #    })
            items = sorted(items, key=lambda x: x['name'])
        return items,total

    # Get the top-level items and their sub-items
    all_items_hierarchy,total = build_item_hierarchy(HOUSE_ROOT)

    return templates.TemplateResponse(
        request,
        "all_items.html",
        {
            "items": all_items_hierarchy,
            "total_items": total
        }
    )


@app.get("/edit/{path:path}", response_class=HTMLResponse)
async def edit_item(request: Request, path: str = ""):
    item_path = HOUSE_ROOT / path

    # Check if the path exists
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")

    # Get item metadata
    metadata = read_index_file(item_path)

    return templates.TemplateResponse(
        request,
        "edit.html",
        {
            "path": path,
            "metadata": metadata
        }
    )


@app.post("/save/{path:path}")
async def save_item(path: str, name: str = Form(...), content: str = Form(default=""), photo: UploadFile = File(...)):
    name = name.strip()
    item_path = HOUSE_ROOT / path
    index_path = item_path / "index.md"

    # Check if the path exists
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")

    if path == "" and name != settings.data_dir:
        raise HTTPException(status_code=403, detail="Cannot rename house name")

    # Get existing metadata to preserve ID
    try:
        metadata = read_index_file(item_path)
        item_id = metadata.get("id", "")
    except Exception:
        item_id = ""

    # If no ID, generate one
    if not item_id:
        item_id = generate_id()

    # Create YAML front matter
    front_matter = yaml.dump({"id": item_id})

    # Write to index.md
    with open(index_path, "w") as f:
        f.write(f"---\n{front_matter}---\n{content}")

    if os.path.basename(item_path) != name:
        new_path = Path(os.path.dirname(item_path)) / name
        if new_path.exists():
            raise HTTPException(status_code=409, detail=f"An item named '{name}' already exists here")
        try:
            os.rename(item_path, new_path)
            path = Path(os.path.dirname(path)) / name
        except:
            raise HTTPException(
                status_code=503, detail="Failed to rename item")

    if photo.size > 0:
        if photo.content_type in ['image/png', 'image/jpeg']:
            # if photo.content_type == 'image/png':
            #    file_path = Path(item_path) / 'photo.png'
            # else:
            file_path = Path(item_path) / 'photo.jpg'
            with open(file_path, "wb") as f:
                shutil.copyfileobj(photo.file, f)

            # Delete thumbnail so it can be regenerated
            thumbnail_path = Path(item_path) / 'thumbnail.jpg'
            if thumbnail_path.exists():
                os.remove(thumbnail_path)
        else:
            return HTTPException(status_code=503, detail="photo not a photo, item edited with no photo")

    git_backup.git_auto_backup("update", name, str(path), HOUSE_ROOT)
    return RedirectResponse(url=f"/browse/{path}", status_code=303)


@app.get("/new/{path:path}", response_class=HTMLResponse)
async def new_item_form(request: Request, path: str = ""):
    parent_path = HOUSE_ROOT / path

    # Check if the parent path exists
    if not parent_path.exists():
        raise HTTPException(status_code=404, detail="Parent item not found")

    return templates.TemplateResponse(
        request,
        "new.html",
        {
            "parent": os.path.basename(parent_path),
            "parent_path": path
        }
    )


@app.post("/delete/{parent_path:path}")
async def delete_item(parent_path: str):
    # Get the item path to be deleted
    item_to_delete_path = HOUSE_ROOT / parent_path

    if item_to_delete_path == HOUSE_ROOT:
        raise HTTPException(
            status_code=500, detail="You can't delete the root item")

    # Check if the item to delete exists
    if not item_to_delete_path.exists() or not item_to_delete_path.is_dir():
        raise HTTPException(status_code=404, detail="Item not found")

    # Get the parent path of the item to delete
    parent_item_path = item_to_delete_path.parent

    # Get the list of sub-items in the item to be deleted
    sub_items_to_move, _ = list_directory_items(item_to_delete_path)

    # Move sub-items to the parent directory
    for sub_item in sub_items_to_move:
        sub_item_path = HOUSE_ROOT / sub_item['path']
        new_location = parent_item_path / sub_item['name']

        try:
            # Move the sub-item
            sub_item_path.rename(new_location)
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error moving sub-item: {str(e)}")

    # Delete the item after moving sub-items
    try:
        shutil.rmtree(item_to_delete_path)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error deleting item: {str(e)}")

    git_backup.git_auto_backup("delete", os.path.basename(parent_path), parent_path, HOUSE_ROOT)
    return RedirectResponse(url=f"/browse/{parent_item_path.relative_to(HOUSE_ROOT)}", status_code=303)


@app.post("/create/{parent_path:path}")
async def create_item(
        parent_path: str,
        name: str = Form(...),
        content: str = Form(default=""),
        photo: UploadFile = File(...),
        go: str = Form(...),
        label: str = Form(...)
):
    folder_name = name.strip()

    if not folder_name:
        return HTTPException(status_code=503, detail="Provide a name")

    if '?' in folder_name:
        return HTTPException(status_code=503, detail="? not allowed in name")

    # Generate a unique ID
    item_id = generate_id()

    # Create the item directory
    item_path = HOUSE_ROOT / parent_path / folder_name
    if item_path.exists():
        raise HTTPException(status_code=409, detail=f"An item named '{folder_name}' already exists here")
    item_path.mkdir(parents=True)

    # Create an index.md file with basic metadata
    index_path = item_path / "index.md"

    # Create YAML front matter
    front_matter = yaml.dump({"name": name, "id": item_id})

    # Write to index.md
    with open(index_path, "w") as f:
        f.write(f"---\n{front_matter}---\n{content}")

    if photo.size > 0:
        if photo.content_type in ['image/png', 'image/jpeg']:
            if photo.content_type == 'image/png':
                file_path = Path(item_path) / 'photo.png'
            else:
                file_path = Path(item_path) / 'photo.jpg'
            with open(file_path, "wb") as f:
                shutil.copyfileobj(photo.file, f)
        else:
            return HTTPException(status_code=503, detail="photo not a photo, item created with no photo")

    if label == 'yes':
        barcode_img = generate_barcode(item_id)
        send_to_printer(barcode_img)
    elif label == 'yes, with text':
        barcode_img = generate_barcode_with_label(item_id, name)
        send_to_printer(barcode_img)

    git_backup.git_auto_backup("create", folder_name, str(Path(parent_path) / folder_name), HOUSE_ROOT)
    redirect_path = Path(parent_path) / folder_name
    if go == 'true':
        return RedirectResponse(url=f"/browse/{redirect_path}", status_code=303)
    else:
        return RedirectResponse(url=f"/new/{parent_path}", status_code=303)


@app.post("/upload/{path:path}")
async def upload_file(path: str, file: UploadFile = File(...)):
    item_path = HOUSE_ROOT / path

    # Check if the path exists
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")

    # Save the uploaded file
    file_path = item_path / file.filename

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    git_backup.git_auto_backup("upload", os.path.basename(path), path, HOUSE_ROOT)
    return RedirectResponse(url=f"/browse/{path}", status_code=303)


@app.get("/delete-attachment/{path:path}")
async def delete_attachment(path: str):
    file_path = HOUSE_ROOT / path

    # Check if the file exists
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Get the parent directory
    parent_path = str(file_path.parent.relative_to(HOUSE_ROOT))

    # Delete the file
    os.remove(file_path)

    git_backup.git_auto_backup("delete_attachment", os.path.basename(parent_path), parent_path, HOUSE_ROOT)
    return RedirectResponse(url=f"/browse/{parent_path}", status_code=303)


@app.get("/download/{path:path}")
async def download_file(path: str):
    # Ensure that the resolved absolute path is within the HOUSE_ROOT directory
    file_path = HOUSE_ROOT / path

    absolute_path = file_path.resolve()

    # Ensure that the resolved absolute path is within the HOUSE_ROOT directory
    if not str(absolute_path).startswith(str(HOUSE_ROOT.resolve())):
        raise HTTPException(
            status_code=403, detail="Access to this file is forbidden")

    # Check if the file exists
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path, filename=file_path.name)


@app.get("/view/{path:path}")
async def view_file(path: str):
    """Serve a file inline (no Content-Disposition: attachment) so the browser can render it."""
    file_path = HOUSE_ROOT / path
    if not str(file_path.resolve()).startswith(str(HOUSE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Access to this file is forbidden")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@app.get("/view-md/{path:path}")
async def view_markdown(request: Request, path: str):
    """Render a markdown attachment as HTML using the app stylesheet."""
    file_path = HOUSE_ROOT / path
    if not str(file_path.resolve()).startswith(str(HOUSE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Access to this file is forbidden")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    html_content = markdown.markdown(file_path.read_text(encoding="utf-8"))
    return templates.TemplateResponse(request, "view_md.html", {"html_content": html_content})


@app.post("/rename-attachment/{path:path}")
async def rename_attachment(path: str, new_name: str = Form(...)):
    file_path = HOUSE_ROOT / path
    if not str(file_path.resolve()).startswith(str(HOUSE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Access to this file is forbidden")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    new_name = new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    new_path = file_path.parent / new_name
    if new_path.exists():
        raise HTTPException(status_code=409, detail="A file with that name already exists")
    file_path.rename(new_path)
    parent_path = str(file_path.parent.relative_to(HOUSE_ROOT))
    git_backup.git_auto_backup("upload", os.path.basename(parent_path), parent_path, HOUSE_ROOT)
    return RedirectResponse(url=f"/browse/{parent_path}", status_code=303)


@app.get("/thumbnail/{path:path}")
async def download_file(path: str):
    item_dir = HOUSE_ROOT / path
    if (item_dir / 'photo.jpg').is_file():
        file_path = item_dir / 'photo.jpg'
    elif (item_dir / 'photo.png').is_file():
        file_path = item_dir / 'photo.png'
    else:
        raise HTTPException(status_code=404, detail="File not found")

    thumbnail_path = Path(os.path.dirname(file_path)) / 'thumbnail.jpg'

    if not thumbnail_path.exists():
        try:
            im = Image.open(file_path, formats=['PNG', 'JPEG'])
            im = ImageOps.exif_transpose(im)
            # Get the original width and height
            width, height = im.size

            # Determine the new dimensions (the smallest dimension of the image)
            new_dim = min(width, height)

            # Calculate the left, top, right, and bottom coordinates for the crop box
            left = (width - new_dim) // 2
            top = (height - new_dim) // 2
            right = (width + new_dim) // 2
            bottom = (height + new_dim) // 2
            im = im.crop((left, top, right, bottom))
            im.thumbnail((128, 128))
            im = im.convert('RGB') # allow save as jpeg
            im.save(thumbnail_path, format="JPEG")
        except IOError:
            raise HTTPException(
                status_code=503, detail="File rendering failed")

        img_byte_arr = BytesIO()
        im.save(img_byte_arr, format="JPEG")
        img_byte_arr.seek(0)

    else:
        with open(thumbnail_path, "rb") as image:
            f = image.read()
            img_byte_arr = BytesIO(f)
            img_byte_arr.seek(0)

    return StreamingResponse(img_byte_arr, media_type="image/jpeg")

# Barcode generators


@app.get("/barcode/{path:path}")
async def barcode_file(path: str):
    item_path = HOUSE_ROOT / path
    metadata = read_index_file(item_path)
    if not metadata:
        raise HTTPException(status_code=404, detail="Item not found")
    id = metadata.get("id")
    barcode_img = generate_barcode(id)
    send_to_printer(barcode_img)
    img_byte_arr = BytesIO()
    barcode_img.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return StreamingResponse(img_byte_arr, media_type="image/png")


def generate_barcode_with_label(item_id, item_name, due_date: str = None):
    # Generate barcode image
    barcode_img = generate_barcode(item_id)

    # Set your desired font size
    font = ImageFont.truetype("roboto.ttf", size=settings.barcode_rendered_height//2)
    font_dd = ImageFont.truetype("roboto.ttf", size=settings.barcode_rendered_height//3)

    # Calculate the scaling factor based on the desired height
    barcode_height = barcode_img.height
    scale_factor = settings.barcode_rendered_height / barcode_height

    # Scale the barcode to the desired height while maintaining the aspect ratio
    barcode_width = int(barcode_img.width * scale_factor)
    barcode_img = barcode_img.resize((barcode_width, settings.barcode_rendered_height))

    # Calculate the width and height of the text
    image = Image.new('RGB', (100, 100))  # You can use any size for the image
    draw = ImageDraw.Draw(image)
    text_bbox = draw.textbbox((0, 0), item_name, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    if due_date:
        text_bbox = draw.textbbox((0, 0), due_date, font=font_dd)
        text_width_dd = text_bbox[2] - text_bbox[0]
        text_height_dd = text_bbox[3] - text_bbox[1]
        if text_width_dd > text_width:
            text_width = text_width_dd

    # Create a blank canvas for the final image (barcode + label)
    canvas_width = barcode_img.width + text_width + \
        10  # Width for the label and barcode
    canvas_height = settings.barcode_rendered_height  # Fixed height for the barcode
    canvas = Image.new('RGB', (canvas_width, canvas_height),
                       color=(255, 255, 255))  # Extra space for the label

    # Paste the scaled barcode image onto the canvas
    canvas.paste(barcode_img, (0, 0))

    # Draw the item name label below the barcode
    draw = ImageDraw.Draw(canvas)

    if not due_date:
        # Position the text dynamically below the barcode
        text_x = barcode_img.width
        text_y = (barcode_img.height - text_height) // 2

        draw.text((text_x, text_y), item_name, fill="black", font=font)
    else:
        # Position the text dynamically below the barcode
        text_x = barcode_img.width
        text_y = (barcode_img.height) // 2

        draw.text((text_x, 0), item_name, fill="black", font=font)
        draw.text((text_x, text_y), due_date, fill="black", font=font_dd)


    # Save the final image to a BytesIO stream
    canvas = canvas.transpose(Image.ROTATE_90)

    return canvas


@app.get("/barcode-with-label/{path:path}")
async def barcode_with_label(path: str):
    item_path = HOUSE_ROOT / path 
    metadata = read_index_file(item_path)
    item_name = metadata.get("name")
    item_id = metadata.get("id")

    if not item_id:
        raise HTTPException(status_code=404, detail="Item ID not found")

    canvas = generate_barcode_with_label(item_id, item_name)
    send_to_printer(canvas)
    img_byte_arr = BytesIO()
    canvas.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)

    # Return the image as a streaming response
    return StreamingResponse(img_byte_arr, media_type="image/png")


def fuzzy_search(query, items, attachments):
    results = {}

    # Search in item names
    item_names = [item["name"] for item in items]

    item_matches = process.extract(
        query, item_names, limit=5, scorer=fuzz.partial_ratio)

    for match in item_matches:
        matched_item = next(item for item in items if item["name"] == match[0])
        if matched_item["name"] not in results.keys():
            results[matched_item['name']] = {
                "type": "item",
                "name": matched_item["name"],
                "path": matched_item["path"],
                "score": match[1]
            }

    # Search in item content
    for item in items:
        metadata = read_index_file(HOUSE_ROOT / item["path"])
        content_score = fuzz.partial_ratio(query, metadata["content"])
        # 50 is the threshold, you can adjust it
        if content_score > 50 and item["name"] not in results.keys():
            results[item["name"]] = {
                "type": "item_content",
                "name": item["name"],
                "path": item["path"],
                "score": content_score
            }
        elif content_score > 50 and results[item['name']]['score'] < content_score:
            results[item['name']]['score'] = content_score

    # Search in attachment names
    attachment_names = [attachment["name"] for attachment in attachments]
    attachment_matches = process.extract(
        query, attachment_names, limit=5, scorer=fuzz.partial_ratio)

    for match in attachment_matches:
        matched_attachment = next(
            att for att in attachments if att["name"] == match[0])
        if match[1] > 5 and matched_attachment['owner'] not in results.keys():
            results[matched_attachment['owner']] = {
                "type": "attachment",
                "name": matched_attachment["owner"],
                "path": matched_attachment["parent_path"],
                "score": match[1]
            }
        elif match[1] > 5 and results[matched_attachment['owner']]['score'] < match[1]:
            results[matched_attachment['owner']]['score'] = match[1]

    # Sort results by score
    # results.sort(key=lambda x: x["score"], reverse=True)
    results = sorted(
        results.items(), key=lambda k: k[1]['score'], reverse=True)
    return results


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, query: str):
    if len(query) == UUID_LENGTH:
        path = find_item_by_id(query)
        if path:
            return RedirectResponse(url=f"/browse/{path.relative_to(HOUSE_ROOT)}", status_code=303)

    # Get all items and attachments
    items, attachments = list_all_items(HOUSE_ROOT)

    # Perform fuzzy search
    search_results = [item[1]
                      for item in fuzzy_search(query, items, attachments)]

    return templates.TemplateResponse(request, "search_results.html", {
        "query": query,
        "results": search_results
    })


@app.get("/by-id/{item_id}", response_class=HTMLResponse)
async def browse_by_id(request: Request, item_id: str):
    # Search for the item based on ID
    item_path = find_item_by_id(item_id)

    # If the item is not found, return a 404 error
    if not item_path:
        raise HTTPException(
            status_code=404, detail="Item with the specified ID not found")

    # Redirect to the browse route with the found path
    return RedirectResponse(url=f"/browse/{item_path.relative_to(HOUSE_ROOT)}", status_code=303)


def find_item_by_id(item_id: str):
    """
    Helper function to find an item by its ID. Returns the path of the item if found, None otherwise.
    """
    for path in [HOUSE_ROOT] + list(HOUSE_ROOT.rglob('*')):  # Iterate over all files and directories in the HOUSE_ROOT
        if path.is_dir():
            try:
                metadata = read_index_file(path)
                if metadata.get("id") == item_id:
                    return path  # Return the path if ID matches
            except Exception:
                # If we can't read the metadata, just continue
                continue
    return None  # Return None if no match is found


@app.get("/move/{item_path:path}", response_class=HTMLResponse)
async def move_item_select(request: Request, item_path: str = ""):
    item_path_obj = HOUSE_ROOT / item_path

    # Check if the item exists
    if not item_path_obj.exists():
        raise HTTPException(status_code=404, detail="Item not found")

    # List all items in the root directory for selection
    all_items, _ = list_all_items(HOUSE_ROOT)

    return templates.TemplateResponse(
        request,
        "move_item.html",
        {
            "item_path": item_path,
            "item_name": os.path.basename(item_path),
            "items": all_items,
        }
    )


@app.post("/move/{item_path:path}")
async def move_item(request: Request, item_path: str, destination: str = Form(default=""), by_id: str = Form(default="")):
    item_path_obj = HOUSE_ROOT / item_path
    if by_id:
        destination_path_obj = find_item_by_id(by_id)
        destination = destination_path_obj.relative_to(HOUSE_ROOT)
    else:
        destination_path_obj = HOUSE_ROOT / destination

    # Check if both the item and destination exist
    if not item_path_obj.exists():
        raise HTTPException(status_code=404, detail="Item not found")

    if not destination_path_obj.exists():
        raise HTTPException(status_code=404, detail="Destination not found")

    # Ensure the destination is a directory
    if not destination_path_obj.is_dir():
        raise HTTPException(
            status_code=400, detail="Destination must be a directory")

    try:
        # Move the item to the selected destination
        new_location = destination_path_obj / item_path_obj.name
        item_path_obj.rename(new_location)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error moving item: {str(e)}")

    git_backup.git_auto_backup("move", item_path_obj.name, str(destination), HOUSE_ROOT)
    return RedirectResponse(url=f"/browse/{destination}", status_code=303)

# see https://github.com/sam159/brotherql_grocylabels/blob/main/app/__init__.py


def send_to_printer(image: Image):
    backend_class, label_spec = get_printer_backend()
    bql = BrotherQLRaster(settings.barcode_printer_model)

    create_label(
        bql,
        image,
        settings.barcode_printer_tape,
        red=label_spec.color == Color.BLACK_RED_WHITE
    )

    be = backend_class(settings.barcode_printer_address)
    be.write(bql.data)
    del be


@app.post("/print_grocy")
async def print_grocy(payload: Dict[Any, Any]):
    response = {"success": "false"}

    try:
        grocycode = payload['grocycode']
        product = payload['product']
        due_date = payload['due_date']
        if due_date:
            canvas = generate_barcode_with_label(grocycode, product, due_date)
        else:
            canvas = generate_barcode_with_label(grocycode, product)
        send_to_printer(canvas)
        response = {"success": "true"}
    except:
        pass


    return response

@app.get("/git-status")
async def git_status_endpoint():
    return git_backup.git_status(HOUSE_ROOT)


# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=True)
