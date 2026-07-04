import logging
import os
import urllib.parse
import yaml
import shutil
import markdown
from io import BytesIO
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps
import storage
import barcode as barcode_mod
import git_backup
from config import settings

router = APIRouter()
templates = Jinja2Templates(directory="templates")
log = logging.getLogger(__name__)


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/all-items/")


@router.get("/browse/{path:path}", response_class=HTMLResponse)
async def browse(request: Request, path: str = ""):
    item_path = storage.HOUSE_ROOT / path

    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")

    metadata = storage.read_index_file(item_path)
    items, attachments = storage.list_directory_items(item_path)

    siblings = None
    if item_path != storage.HOUSE_ROOT:
        siblings, _ = storage.list_directory_items(Path(os.path.dirname(item_path)))
        siblings = [s for s in siblings if s.get('name') != metadata.get('name')]
        siblings = sorted(siblings, key=lambda x: x['name'])

    items = sorted(items, key=lambda x: x['name'])

    breadcrumbs = [{"name": "House", "path": ""}]
    current_path = Path("")
    for part in Path(path).parts:
        current_path = current_path / part
        breadcrumbs.append({"name": part, "path": str(current_path)})

    return templates.TemplateResponse(request, "item.html", {
        "path": path,
        "metadata": metadata,
        "items": items,
        "siblings": siblings,
        "attachments": attachments,
        "breadcrumbs": breadcrumbs,
    })


@router.get("/all-items", response_class=HTMLResponse)
async def all_items(request: Request):
    all_items_hierarchy, total = storage.get_hierarchy()
    return templates.TemplateResponse(request, "all_items.html", {
        "items": all_items_hierarchy,
        "total_items": total,
    })


@router.get("/edit/{path:path}", response_class=HTMLResponse)
async def edit_item(request: Request, path: str = ""):
    item_path = storage.HOUSE_ROOT / path
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    metadata = storage.read_index_file(item_path)
    return templates.TemplateResponse(request, "edit.html", {"path": path, "metadata": metadata})


@router.post("/save/{path:path}")
async def save_item(path: str, name: str = Form(...), content: str = Form(default=""), photo: UploadFile = File(...)):
    name = name.strip()
    item_path = storage.HOUSE_ROOT / path
    index_path = item_path / "index.md"

    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")

    if path == "" and name != settings.data_dir:
        raise HTTPException(status_code=403, detail="Cannot rename house name")

    try:
        metadata = storage.read_index_file(item_path)
        item_id = metadata.get("id", "")
    except Exception:
        log.warning("Could not read existing metadata for %s, generating new ID", item_path)
        item_id = ""

    if not item_id:
        item_id = storage.generate_id()

    with open(index_path, "w") as f:
        f.write(f"---\n{yaml.dump({'id': item_id})}---\n{content}")

    if os.path.basename(item_path) != name:
        new_path = Path(os.path.dirname(item_path)) / name
        if new_path.exists():
            raise HTTPException(status_code=409, detail=f"An item named '{name}' already exists here")
        try:
            os.rename(item_path, new_path)
            path = Path(os.path.dirname(path)) / name
        except Exception:
            log.exception("Failed to rename %s to %s", item_path, new_path)
            raise HTTPException(status_code=503, detail="Failed to rename item")

    if photo.size > 0:
        if photo.content_type in ['image/png', 'image/jpeg']:
            file_path = Path(item_path) / 'photo.jpg'
            with open(file_path, "wb") as f:
                shutil.copyfileobj(photo.file, f)
            thumbnail_path = Path(item_path) / 'thumbnail.jpg'
            if thumbnail_path.exists():
                os.remove(thumbnail_path)
        else:
            return HTTPException(status_code=503, detail="photo not a photo, item edited with no photo")

    log.info("Saved item %s", name)
    git_backup.git_auto_backup("update", name, str(path), storage.HOUSE_ROOT)
    storage._invalidate_hierarchy()
    return RedirectResponse(url=f"/browse/{path}", status_code=303)


@router.get("/new/{path:path}", response_class=HTMLResponse)
async def new_item_form(request: Request, path: str = "", added: str = "", added_path: str = ""):
    parent = storage.HOUSE_ROOT / path
    if not parent.exists():
        raise HTTPException(status_code=404, detail="Location not found")

    children, _ = storage.list_directory_items(parent)
    children = sorted(children, key=lambda x: x['name'])

    siblings = []
    if parent != storage.HOUSE_ROOT:
        sibling_items, _ = storage.list_directory_items(parent.parent)
        siblings = sorted(
            [s for s in sibling_items if s['name'] != os.path.basename(parent)],
            key=lambda x: x['name'],
        )

    breadcrumbs = [{"name": settings.data_dir, "path": ""}]
    current = Path("")
    for part in Path(path).parts:
        current = current / part
        breadcrumbs.append({"name": part, "path": str(current)})

    return templates.TemplateResponse(request, "new.html", {
        "parent": os.path.basename(parent) or settings.data_dir,
        "parent_path": path,
        "added": added,
        "added_path": added_path,
        "children": children,
        "siblings": siblings,
        "breadcrumbs": breadcrumbs,
    })


@router.post("/new/{path:path}")
async def create_item(
    path: str = "",
    name: str = Form(...),
    content: str = Form(default=""),
    photo: Optional[UploadFile] = File(default=None),
    label: str = Form(default="no"),
):
    folder_name = name.strip()
    if not folder_name:
        raise HTTPException(status_code=400, detail="Name required")
    if '?' in folder_name:
        raise HTTPException(status_code=400, detail="? not allowed in name")

    item_path = storage.HOUSE_ROOT / path / folder_name
    if item_path.exists():
        raise HTTPException(status_code=409, detail=f"'{folder_name}' already exists here")
    item_path.mkdir(parents=True)

    item_id = storage.generate_id()
    (item_path / "index.md").write_text(
        f"---\n{yaml.dump({'name': folder_name, 'id': item_id})}---\n{content}")

    if photo and photo.size > 0:
        if photo.content_type in ['image/png', 'image/jpeg']:
            ext = 'png' if photo.content_type == 'image/png' else 'jpg'
            with open(item_path / f'photo.{ext}', "wb") as f:
                shutil.copyfileobj(photo.file, f)

    if label == 'yes':
        barcode_mod.send_to_printer(barcode_mod.generate_barcode(item_id))
    elif label == 'yes, with text':
        barcode_mod.send_to_printer(barcode_mod.generate_barcode_with_label(item_id, folder_name))

    log.info("Created item %s (id=%s) under %r", folder_name, item_id, path or "/")
    git_backup.git_auto_backup("create", folder_name, str(Path(path) / folder_name), storage.HOUSE_ROOT)
    storage._invalidate_hierarchy()

    added_path_str = str(Path(path) / folder_name)
    return RedirectResponse(
        url=f"/new/{path}?added={urllib.parse.quote(folder_name)}&added_path={urllib.parse.quote(added_path_str)}",
        status_code=303,
    )


@router.post("/delete/{parent_path:path}")
async def delete_item(parent_path: str):
    item_to_delete_path = storage.HOUSE_ROOT / parent_path

    if item_to_delete_path == storage.HOUSE_ROOT:
        raise HTTPException(status_code=500, detail="You can't delete the root item")

    if not item_to_delete_path.exists() or not item_to_delete_path.is_dir():
        raise HTTPException(status_code=404, detail="Item not found")

    parent_item_path = item_to_delete_path.parent
    sub_items_to_move, _ = storage.list_directory_items(item_to_delete_path)

    for sub_item in sub_items_to_move:
        sub_item_path = storage.HOUSE_ROOT / sub_item['path']
        try:
            sub_item_path.rename(parent_item_path / sub_item['name'])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error moving sub-item: {str(e)}")

    try:
        shutil.rmtree(item_to_delete_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting item: {str(e)}")

    log.info("Deleted item %s", parent_path)
    git_backup.git_auto_backup("delete", os.path.basename(parent_path), parent_path, storage.HOUSE_ROOT)
    storage._invalidate_hierarchy()
    return RedirectResponse(url=f"/browse/{parent_item_path.relative_to(storage.HOUSE_ROOT)}", status_code=303)


@router.post("/upload/{path:path}")
async def upload_file(path: str, file: UploadFile = File(...)):
    item_path = storage.HOUSE_ROOT / path
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    with open(item_path / file.filename, "wb") as f:
        shutil.copyfileobj(file.file, f)
    git_backup.git_auto_backup("upload", os.path.basename(path), path, storage.HOUSE_ROOT)
    return RedirectResponse(url=f"/browse/{path}", status_code=303)


@router.get("/delete-attachment/{path:path}")
async def delete_attachment(path: str):
    file_path = storage.HOUSE_ROOT / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    parent_path = str(file_path.parent.relative_to(storage.HOUSE_ROOT))
    os.remove(file_path)
    git_backup.git_auto_backup("delete_attachment", os.path.basename(parent_path), parent_path, storage.HOUSE_ROOT)
    return RedirectResponse(url=f"/browse/{parent_path}", status_code=303)


@router.get("/download/{path:path}")
async def download_file(path: str):
    file_path = storage.HOUSE_ROOT / path
    if not str(file_path.resolve()).startswith(str(storage.HOUSE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Access to this file is forbidden")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=file_path.name)


@router.get("/view/{path:path}")
async def view_file(path: str):
    file_path = storage.HOUSE_ROOT / path
    if not str(file_path.resolve()).startswith(str(storage.HOUSE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Access to this file is forbidden")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@router.get("/view-md/{path:path}")
async def view_markdown(request: Request, path: str):
    file_path = storage.HOUSE_ROOT / path
    if not str(file_path.resolve()).startswith(str(storage.HOUSE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Access to this file is forbidden")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    html_content = markdown.markdown(file_path.read_text(encoding="utf-8"))
    return templates.TemplateResponse(request, "view_md.html", {"html_content": html_content})


@router.post("/rename-attachment/{path:path}")
async def rename_attachment(path: str, new_name: str = Form(...)):
    file_path = storage.HOUSE_ROOT / path
    if not str(file_path.resolve()).startswith(str(storage.HOUSE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Access to this file is forbidden")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    new_name = new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    original_ext = file_path.suffix
    if original_ext and new_name.endswith(original_ext):
        new_stem = new_name[:-len(original_ext)]
    else:
        new_stem = new_name
    new_path = file_path.parent / (new_stem + original_ext)
    if new_path.exists() and new_path != file_path:
        raise HTTPException(status_code=409, detail="A file with that name already exists")
    file_path.rename(new_path)
    parent_path = str(file_path.parent.relative_to(storage.HOUSE_ROOT))
    git_backup.git_auto_backup("rename_attachment", os.path.basename(parent_path), parent_path, storage.HOUSE_ROOT)
    return RedirectResponse(url=f"/browse/{parent_path}", status_code=303)


@router.get("/thumbnail/{path:path}")
async def thumbnail(path: str):
    item_dir = storage.HOUSE_ROOT / path
    if (item_dir / 'photo.jpg').is_file():
        file_path = item_dir / 'photo.jpg'
    elif (item_dir / 'photo.png').is_file():
        file_path = item_dir / 'photo.png'
    else:
        raise HTTPException(status_code=404, detail="File not found")

    thumbnail_path = file_path.parent / 'thumbnail.jpg'

    if not thumbnail_path.exists():
        try:
            im = Image.open(file_path, formats=['PNG', 'JPEG'])
            im = ImageOps.exif_transpose(im)
            width, height = im.size
            new_dim = min(width, height)
            left = (width - new_dim) // 2
            top = (height - new_dim) // 2
            im = im.crop((left, top, left + new_dim, top + new_dim))
            im.thumbnail((128, 128))
            im = im.convert('RGB')
            im.save(thumbnail_path, format="JPEG")
        except IOError:
            raise HTTPException(status_code=503, detail="File rendering failed")

        img_byte_arr = BytesIO()
        im.save(img_byte_arr, format="JPEG")
        img_byte_arr.seek(0)
    else:
        img_byte_arr = BytesIO(thumbnail_path.read_bytes())
        img_byte_arr.seek(0)

    return StreamingResponse(img_byte_arr, media_type="image/jpeg")


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, query: str):
    if len(query) == storage.UUID_LENGTH:
        path = storage.find_item_by_id(query)
        if path:
            return RedirectResponse(
                url=f"/browse/{path.relative_to(storage.HOUSE_ROOT)}", status_code=303)

    items, attachments = storage.list_all_items(storage.HOUSE_ROOT)
    search_results = [item[1] for item in storage.fuzzy_search(query, items, attachments)]
    return templates.TemplateResponse(request, "search_results.html", {
        "query": query,
        "results": search_results,
    })


@router.get("/by-id/{item_id}", response_class=HTMLResponse)
async def browse_by_id(request: Request, item_id: str):
    item_path = storage.find_item_by_id(item_id)
    if not item_path:
        raise HTTPException(status_code=404, detail="Item with the specified ID not found")
    return RedirectResponse(
        url=f"/browse/{item_path.relative_to(storage.HOUSE_ROOT)}", status_code=303)


@router.get("/move/{item_path:path}", response_class=HTMLResponse)
async def move_item_select(request: Request, item_path: str = ""):
    item_path_obj = storage.HOUSE_ROOT / item_path
    if not item_path_obj.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    all_items, _ = storage.list_all_items(storage.HOUSE_ROOT)
    return templates.TemplateResponse(request, "move_item.html", {
        "item_path": item_path,
        "item_name": os.path.basename(item_path),
        "items": all_items,
    })


@router.post("/move/{item_path:path}")
async def move_item(request: Request, item_path: str, destination: str = Form(default=""), by_id: str = Form(default="")):
    item_path_obj = storage.HOUSE_ROOT / item_path
    if by_id:
        destination_path_obj = storage.find_item_by_id(by_id)
        destination = destination_path_obj.relative_to(storage.HOUSE_ROOT)
    else:
        destination_path_obj = storage.HOUSE_ROOT / destination

    if not item_path_obj.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    if not destination_path_obj.exists():
        raise HTTPException(status_code=404, detail="Destination not found")
    if not destination_path_obj.is_dir():
        raise HTTPException(status_code=400, detail="Destination must be a directory")

    try:
        item_path_obj.rename(destination_path_obj / item_path_obj.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error moving item: {str(e)}")

    log.info("Moved %s to %s", item_path, destination)
    git_backup.git_auto_backup("move", item_path_obj.name, str(destination), storage.HOUSE_ROOT)
    storage._invalidate_hierarchy()
    return RedirectResponse(url=f"/browse/{destination}", status_code=303)


@router.get("/git-status")
async def git_status_endpoint():
    return git_backup.git_status(storage.HOUSE_ROOT)
