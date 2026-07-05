import logging
import os
import shutil
import yaml
from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Security, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
import storage
import git_backup
import barcode as barcode_mod
from config import settings

log = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(key: str = Security(api_key_header)):
    if not settings.api_key:
        return
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])


class CreateItem(BaseModel):
    name: str
    content: str = ""
    fields: dict[str, Any] = {}


class UpdateItem(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    fields: Optional[dict[str, Any]] = None


class MoveItem(BaseModel):
    destination: str
    by_id: bool = False


def _serialize(obj: dict) -> dict:
    return {k: str(v) if isinstance(v, Path) else v
            for k, v in obj.items() if k != "html_content"}


def _serialize_tree(nodes: list) -> list:
    result = []
    for node in nodes:
        result.append({
            "id": node.get("id", ""),
            "name": node["name"],
            "path": str(node["path"]),
            "children": _serialize_tree(node.get("sub_items", [])),
        })
    return result


# Specific sub-resource routes must be registered before the general /{path:path}
# routes so Starlette matches them before the greedy path catch-all.

@router.post("/items/{path:path}/photo", status_code=201)
async def upload_photo(path: str, file: UploadFile = File(...)):
    """Upload or replace the photo for an item. Accepts image/jpeg or image/png."""
    item_path = storage.HOUSE_ROOT / path
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=415, detail="Only image/jpeg and image/png are accepted")
    ext = "png" if file.content_type == "image/png" else "jpg"
    dest = item_path / f"photo.{ext}"
    if not str(dest.resolve()).startswith(str(storage.HOUSE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Invalid path")
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    thumbnail = item_path / "thumbnail.jpg"
    if thumbnail.exists():
        os.remove(thumbnail)
    log.info("API uploaded photo for %s", path)
    git_backup.git_auto_backup("upload", "photo", path, storage.HOUSE_ROOT)
    storage._invalidate_hierarchy()
    return {"photo_path": f"/download/{path}/photo.{ext}"}


@router.get("/items/{path:path}/photo")
async def get_photo(path: str):
    """Download the photo for an item."""
    item_path = storage.HOUSE_ROOT / path
    for ext in ("jpg", "png"):
        photo = item_path / f"photo.{ext}"
        if photo.exists():
            return FileResponse(photo, media_type=f"image/{ext}", filename=f"photo.{ext}")
    raise HTTPException(status_code=404, detail="No photo for this item")


@router.post("/items/{path:path}/print")
async def print_label(path: str):
    """Print a barcode label for an item. Requires printer to be configured."""
    if not settings.barcode_printer_address:
        raise HTTPException(status_code=503, detail="No printer configured (BARCODE_PRINTER_ADDRESS is not set)")
    item_path = storage.HOUSE_ROOT / path
    metadata = storage.read_index_file(item_path)
    if not metadata:
        raise HTTPException(status_code=404, detail="Item not found")
    item_id = metadata.get("id")
    if not item_id:
        raise HTTPException(status_code=422, detail="Item has no ID")
    canvas = barcode_mod.generate_barcode_with_label(item_id, metadata.get("name", path))
    barcode_mod.send_to_printer(canvas)
    log.info("API printed label for %s (%s)", path, item_id)
    return {"printed": True, "id": item_id, "name": metadata.get("name", path), "path": path}


@router.post("/items/{path:path}/move")
async def move_item(body: MoveItem, path: str):
    item_path = storage.HOUSE_ROOT / path
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    if body.by_id:
        dest_path = storage.find_item_by_id(body.destination)
        if not dest_path:
            raise HTTPException(status_code=404, detail="Destination not found")
    else:
        dest_path = storage.HOUSE_ROOT / body.destination
        if not dest_path.exists():
            raise HTTPException(status_code=404, detail="Destination not found")
    if not dest_path.is_dir():
        raise HTTPException(status_code=400, detail="Destination must be a directory")
    try:
        item_path.rename(dest_path / item_path.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error moving item: {e}")
    new_path = str(dest_path.relative_to(storage.HOUSE_ROOT) / item_path.name)
    log.info("API moved %s to %s", path, body.destination)
    git_backup.git_auto_backup("move", item_path.name, body.destination, storage.HOUSE_ROOT)
    storage._invalidate_hierarchy()
    return {"path": new_path}


@router.post("/items/{path:path}/attachments", status_code=201)
async def upload_attachment(path: str, file: UploadFile = File(...)):
    item_path = storage.HOUSE_ROOT / path
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    dest = item_path / file.filename
    if not str(dest.resolve()).startswith(str(storage.HOUSE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Invalid path")
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    log.info("API uploaded attachment %s to %s", file.filename, path)
    git_backup.git_auto_backup("upload", os.path.basename(path), path, storage.HOUSE_ROOT)
    return {"name": file.filename, "path": str(dest.relative_to(storage.HOUSE_ROOT)), "size": dest.stat().st_size}


@router.get("/items/{path:path}/attachments/{filename}")
async def download_attachment(path: str, filename: str):
    file_path = storage.HOUSE_ROOT / path / filename
    if not str(file_path.resolve()).startswith(str(storage.HOUSE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Access forbidden")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=filename)


@router.delete("/items/{path:path}/attachments/{filename}", status_code=204)
async def delete_attachment(path: str, filename: str):
    file_path = storage.HOUSE_ROOT / path / filename
    if not str(file_path.resolve()).startswith(str(storage.HOUSE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Access forbidden")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    os.remove(file_path)
    log.info("API deleted attachment %s from %s", filename, path)
    git_backup.git_auto_backup("delete_attachment", os.path.basename(path), path, storage.HOUSE_ROOT)
    return Response(status_code=204)


@router.get("/items/{path:path}")
async def get_item(path: str = ""):
    item_path = storage.HOUSE_ROOT / path
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    metadata = storage.read_index_file(item_path) or {}
    children, attachments = storage.list_directory_items(item_path)
    return {
        **_serialize(metadata),
        "children": [_serialize(c) for c in children],
        "attachments": [_serialize(a) for a in attachments],
    }


@router.post("/items/{path:path}", status_code=201)
async def create_item(body: CreateItem, path: str = ""):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    parent = storage.HOUSE_ROOT / path
    if not parent.exists():
        raise HTTPException(status_code=404, detail="Parent not found")
    item_path = parent / name
    if item_path.exists():
        raise HTTPException(status_code=409, detail=f"'{name}' already exists here")
    item_path.mkdir(parents=True)
    item_id = storage.generate_id()
    (item_path / "index.md").write_text(
        f"---\n{yaml.dump({'name': name, 'id': item_id, **body.fields})}---\n{body.content}")
    log.info("API created item %s (id=%s) under %r", name, item_id, path or "/")
    git_backup.git_auto_backup("create", name, str(Path(path) / name), storage.HOUSE_ROOT)
    storage._invalidate_hierarchy()
    return {"id": item_id, "name": name, "path": str(Path(path) / name)}


@router.patch("/items/{path:path}")
async def update_item(body: UpdateItem, path: str = ""):
    item_path = storage.HOUSE_ROOT / path
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    metadata = storage.read_index_file(item_path) or {}
    item_id = metadata.get("id") or storage.generate_id()
    content = body.content if body.content is not None else metadata.get("content", "")
    preserved = {k: v for k, v in metadata.items() if k not in storage.SYSTEM_KEYS}
    if body.fields is not None:
        preserved.update(body.fields)
    (item_path / "index.md").write_text(
        f"---\n{yaml.dump({'id': item_id, **preserved})}---\n{content}")
    new_path = path
    if body.name and body.name.strip() != item_path.name:
        name = body.name.strip()
        dest = item_path.parent / name
        if dest.exists():
            raise HTTPException(status_code=409, detail=f"'{name}' already exists here")
        os.rename(item_path, dest)
        new_path = str(Path(os.path.dirname(path)) / name)
    log.info("API updated item %s", path)
    git_backup.git_auto_backup("update", body.name or item_path.name, new_path, storage.HOUSE_ROOT)
    storage._invalidate_hierarchy()
    return {"path": new_path}


@router.delete("/items/{path:path}", status_code=204)
async def delete_item(path: str):
    item_path = storage.HOUSE_ROOT / path
    if item_path == storage.HOUSE_ROOT:
        raise HTTPException(status_code=403, detail="Cannot delete root")
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    parent = item_path.parent
    children, _ = storage.list_directory_items(item_path)
    for child in children:
        (storage.HOUSE_ROOT / child['path']).rename(parent / child['name'])
    shutil.rmtree(item_path)
    log.info("API deleted item %s", path)
    git_backup.git_auto_backup("delete", item_path.name, path, storage.HOUSE_ROOT)
    storage._invalidate_hierarchy()
    return Response(status_code=204)


@router.get("/tree")
async def get_tree():
    """Return all items as a nested tree (id, name, path, children). No content fields."""
    nodes, total = storage.get_hierarchy()
    return {"total": total, "tree": _serialize_tree(nodes)}


@router.get("/filter")
async def filter_items(field: str, value: str):
    """List all items where a custom field equals the given value (case-insensitive)."""
    items, _ = storage.list_all_items(storage.HOUSE_ROOT)
    results = [
        _serialize(item) for item in items
        if str(item.get(field, "")).lower() == value.lower()
    ]
    return {"field": field, "value": value, "results": results}


@router.get("/fields")
async def list_fields():
    """Return all distinct custom field names and their known values across the inventory."""
    return storage.get_fields()


@router.get("/search")
async def search(query: str):
    if len(query) == storage.UUID_LENGTH:
        found = storage.find_item_by_id(query)
        if found:
            metadata = storage.read_index_file(found) or {}
            return {"type": "id_match", "item": _serialize(metadata)}
    items, attachments = storage.list_all_items(storage.HOUSE_ROOT)
    results = [r[1] for r in storage.fuzzy_search(query, items, attachments)]
    return {"results": [_serialize(r) for r in results]}
