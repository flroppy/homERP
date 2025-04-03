# main.py
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import yaml
import uuid
import base64
import markdown
import shutil
from PIL import Image
from pathlib import Path
from typing import List, Optional
from pylibdmtx.pylibdmtx import encode

# Initialize FastAPI app
app = FastAPI(title="House Inventory App")

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates directory
templates = Jinja2Templates(directory="templates")

# Root directory for house items
HOUSE_ROOT = Path("house")

# Ensure house directory exists
HOUSE_ROOT.mkdir(exist_ok=True)

# Helper function to generate a 6-character base64 ID
def generate_id():
    # Generate a random UUID
    random_id = uuid.uuid4().bytes
    # Encode it to base64 and take the first 6 characters
    base64_id = base64.urlsafe_b64encode(random_id).decode('utf-8')[:6]
    return base64_id

def generate_barcode(item_path, item_id):
    barcode_path = item_path / "barcode.png"

    # Only generate if it doesn't exist or force regenerate
    if not barcode_path.exists() and item_id:
        encoded = encode(item_id.encode('utf8'))
        img = Image.frombytes('RGB',(encoded.width, encoded.height), encoded.pixels)
        img.save(barcode_path)

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

    # Generate barcode if it doesn't exist
    if "id" in metadata and metadata["id"]:
        generate_barcode(item_path, metadata["id"])
    
    return {
        **metadata,
        "content": markdown_text,
        "html_content": markdown.markdown(markdown_text),
        "barcode_path": "download" / item_path.relative_to(HOUSE_ROOT) / "barcode.png"

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
                    "name": metadata.get("name", path.name),
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
        elif path.is_file() and path.name not in ["index.md", "barcode.png"]:
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
    front_matter = yaml.dump({"name": name, "id": item_id})
    
    # Write to index.md
    with open(index_path, "w") as f:
        f.write(f"---\n{front_matter}---\n{content}")

    # Generate barcode
    generate_barcode(item_path, item_id)
    
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

    # Generate barcode
    generate_barcode(item_path, item_id)
    
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

@app.get("/regenerate-barcode/{path:path}")
async def regenerate_barcode(path: str):
    item_path = HOUSE_ROOT / path
    
    # Check if the path exists
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Get item metadata
    metadata = read_index_file(item_path)
    item_id = metadata.get("id", "")
    
    if not item_id:
        raise HTTPException(status_code=400, detail="Item has no ID")
    
    # Remove existing barcode if it exists
    barcode_path = item_path / "barcode.png"
    if barcode_path.exists():
        os.remove(barcode_path)
    
    # Generate new barcode
    generate_barcode(item_path, item_id)
    
    return RedirectResponse(url=f"/browse/{path}", status_code=303)

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
