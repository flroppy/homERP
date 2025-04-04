# main.py
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import yaml
import uuid
import base64
import markdown
import shutil
import re
from io import BytesIO
from PIL import Image
from pathlib import Path
from typing import List, Optional
from pylibdmtx.pylibdmtx import encode
from fuzzywuzzy import fuzz
from fuzzywuzzy import process

# Initialize FastAPI app
app = FastAPI(title="House Inventory App")

# Mount static files directory
#app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates directory
templates = Jinja2Templates(directory="templates")

# Root directory for house items
HOUSE_NAME = "house"
HOUSE_ROOT = Path(HOUSE_NAME)

# Ensure house directory exists
HOUSE_ROOT.mkdir(exist_ok=True)

IGNORED_ATTACHMENTS = ['index.md']

# Helper function to generate a 6-character base64 ID
def generate_id():
    # Generate a random UUID
    random_id = uuid.uuid4().bytes
    # Encode it to base64 and take the first 6 characters
    base64_id = base64.urlsafe_b64encode(random_id).decode('utf-8')[:8]
    return base64_id

def generate_barcode(item_id):
    encoded = encode(item_id.encode('utf8'))
    img = Image.frombytes('RGB',(encoded.width, encoded.height), encoded.pixels)
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

def shift_headings_down(markdown_text):
    # Function to shift headings down by one level
    def shift_heading(heading):
        # Match headings like # Heading, ## Heading, etc.
        match = re.match(r'^(#{1,6})\s+(.*)', heading)
        if match:
            current_level = len(match.group(1))  # Count of '#' determines the heading level
            new_level = min(6, current_level + 1)  # Shift heading up, but not above level 6
            return '#' * new_level + ' ' + match.group(2)  # Create new heading with shifted level
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
        return {"name": item_path.name, "id": ""}
    
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

    markdown_text = shift_headings_down(markdown_text)
    markdown_text = adjust_paths_in_markdown(markdown_text, Path('/download/') / str(item_path)[len(HOUSE_NAME):])

    return {
        **metadata,
        "name": item_path.name,
        "content": markdown_text,
        "html_content": markdown.markdown(markdown_text),
        "barcode_path": "barcode" / item_path.relative_to(HOUSE_ROOT) / "barcode.png"
    }

# Helper function to list items in a directory
def list_directory_items(directory_path):
    items = []
    attachments = []
    
    if not directory_path.exists():
        return items, attachments
    
    for path in directory_path.iterdir():
        if path.is_dir() and path.name != ".git":
            # This is a sub-item
            try:
                metadata = read_index_file(path)
                items.append({
                    "path": path.relative_to(HOUSE_ROOT),
                    "name": path.name,
                    "id": metadata.get("id", ""),
                })
            except Exception:
                # If we can't read the metadata, just use the folder name
                items.append({
                    "path": path.relative_to(HOUSE_ROOT),
                    "name": path.name,
                    "id": "",
                    "barcode_path": False
                })
        elif path.is_file() and path.name not in IGNORED_ATTACHMENTS:
            # This is an attachment
            attachments.append({
                "name": path.name,
                "path": path.relative_to(HOUSE_ROOT),
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
    return RedirectResponse(url="/browse/")

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
    
    # Get breadcrumbs
    breadcrumbs = []
    current_path = Path("")
    breadcrumbs.append({"name": "House", "path": ""})
    
    for part in Path(path).parts:
        current_path = current_path / part
        part_path = HOUSE_ROOT / current_path
        try:
            part_metadata = read_index_file(part_path)
            breadcrumbs.append({
                "name": part_metadata.get("name", part),
                "path": str(current_path)
            })
        except Exception:
            breadcrumbs.append({
                "name": part,
                "path": str(current_path)
            })
    
    return templates.TemplateResponse(
        "item.html", 
        {
            "request": request,
            "path": path,
            "metadata": metadata,
            "items": items,
            "attachments": attachments,
            "breadcrumbs": breadcrumbs
        }
    )

@app.get("/all-items", response_class=HTMLResponse)
async def all_items(request: Request):
    def build_item_hierarchy(directory_path):
        items = []
        
        if not directory_path.exists():
            return items
        
        # TODO: Make this a helper function
        for path in directory_path.iterdir():
            if path.is_dir() and path.name != ".git":
                # This is a directory, add it and recursively fetch sub-items
                try:
                    metadata = read_index_file(path)
                    items.append({
                        "path": path.relative_to(HOUSE_ROOT),
                        "name": metadata.get("name", path.name),
                        "id": metadata.get("id", ""),
                        "sub_items": build_item_hierarchy(path)  # Recursively get sub-items
                    })
                except Exception:
                    # If we can't read the metadata, still list the directory
                    items.append({
                        "path": path.relative_to(HOUSE_ROOT),
                        "name": path.name,
                        "id": "",
                        "sub_items": build_item_hierarchy(path)  # Recursively get sub-items
                    })
            elif path.is_file() and path.name not in ["index.md", "barcode.png"]:
                # This is a file (attachment), we can optionally list them too
                items.append({
                    "name": path.name,
                    "path": path.relative_to(HOUSE_ROOT),
                    "size": path.stat().st_size,
                    "sub_items": []  # No sub-items for files
                })
        
        return items
    
    # Get the top-level items and their sub-items
    all_items_hierarchy = build_item_hierarchy(HOUSE_ROOT)
    
    return templates.TemplateResponse(
        "all_items.html",
        {
            "request": request,
            "items": all_items_hierarchy
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
        "edit.html", 
        {
            "request": request,
            "path": path,
            "metadata": metadata
        }
    )

@app.post("/save/{path:path}")
async def save_item(path: str, name: str = Form(...), content: str = Form(...)):
    item_path = HOUSE_ROOT / path
    index_path = item_path / "index.md"
    
    # Check if the path exists
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")

    if path == "" and name != HOUSE_NAME:
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
        try:
            os.rename(item_path, new_path)
            path = Path(os.path.dirname(path)) / name
        except:
            raise HTTPException(status_code=503, detail="Failed to rename item")

    return RedirectResponse(url=f"/browse/{path}", status_code=303)

@app.get("/new/{path:path}", response_class=HTMLResponse)
async def new_item_form(request: Request, path: str = ""):
    parent_path = HOUSE_ROOT / path
    
    # Check if the parent path exists
    if not parent_path.exists():
        raise HTTPException(status_code=404, detail="Parent item not found")
    
    return templates.TemplateResponse(
        "new.html", 
        {
            "request": request,
            "parent_path": path
        }
    )

@app.post("/create/{parent_path:path}")
async def create_item(parent_path: str, name: str = Form(...), content: str = Form(...)):
    # Create a normalized folder name from the item name
    folder_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in name).strip()
    folder_name = folder_name.replace(" ", "-").lower()
    
    if not folder_name:
        folder_name = generate_id()
    
    # Generate a unique ID
    item_id = generate_id()
    
    # Create the item directory
    item_path = HOUSE_ROOT / parent_path / folder_name
    item_path.mkdir(exist_ok=True, parents=True)
    
    # Create an index.md file with basic metadata
    index_path = item_path / "index.md"
    
    # Create YAML front matter
    front_matter = yaml.dump({"name": name, "id": item_id})
    
    # Write to index.md
    with open(index_path, "w") as f:
        f.write(f"---\n{front_matter}---\n{content}")

    return RedirectResponse(url=f"/browse/{parent_path}/{folder_name}", status_code=303)

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
    
    return RedirectResponse(url=f"/browse/{parent_path}", status_code=303)

@app.get("/download/{path:path}")
async def download_file(path: str):
    file_path = HOUSE_ROOT / path
    
    # Check if the file exists
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(file_path, filename=file_path.name)

@app.get("/barcode/{path:path}")
async def barcode_file(path: str):
    item_path = HOUSE_ROOT / path
    metadata = read_index_file(item_path)
    id = metadata.get("id")
    return StreamingResponse(generate_barcode(id), media_type="image/png")
    


def fuzzy_search(query, items, attachments):
    results = {}
    seen_paths = set()  # To track already added items and attachments

    # Search in item names
    item_names = [item["name"] for item in items]

    item_matches = process.extract(query, item_names, limit=5, scorer=fuzz.partial_ratio)
    
    for match in item_matches:
        matched_item = next(item for item in items if item["name"] == match[0])
        if matched_item["name"] not in results.keys():
            results[matched_item['name']]={
                "type": "item",
                "name": matched_item["name"],
                "path": matched_item["path"],
                "score": match[1]
            }

    # Search in item content
    for item in items:
        metadata = read_index_file(HOUSE_ROOT / item["path"])
        content_score = fuzz.partial_ratio(query, metadata["content"])
        if content_score > 50 and item["name"] not in results.keys():  # 50 is the threshold, you can adjust it
            results.append({
                "type": "item_content",
                "name": item["name"],
                "path": item["path"],
                "score": content_score
            })
            seen_paths.add(item["path"])
        elif results[item['name']]['score'] < content_score:
            results[item['name']]['score'] = content_score

    # Search in attachment names
    attachment_names = [attachment["name"] for attachment in attachments]
    attachment_matches = process.extract(query, attachment_names, limit=5, scorer=fuzz.partial_ratio)
    
    for match in attachment_matches:
        matched_attachment = next(att for att in attachments if att["name"] == match[0])
        if matched_attachment["name"] not in results.keys():
            results.append({
                "type": "attachment",
                "name": matched_attachment["name"],
                "path": matched_attachment["path"],
                "score": match[1]
            })
            seen_paths.add(matched_attachment["path"])
        elif results[matched_attachment['name']]['score'] < match[1]:
            results[matched_attachment['name']]['score'] = match[1]

    # Sort results by score
    #results.sort(key=lambda x: x["score"], reverse=True)
    results = sorted(results.items(), key=lambda k: k[1]['score'], reverse=True)
    return results


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, query: str):
    # Get all items and attachments
    items, attachments = list_all_items(HOUSE_ROOT)

    # Perform fuzzy search
    search_results = [item[1] for item in  fuzzy_search(query, items, attachments)]

    return templates.TemplateResponse("search_results.html", {
        "request": request,
        "query": query,
        "results": search_results
    })

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=True)
