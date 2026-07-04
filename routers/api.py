import logging
import os
import shutil
import yaml
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, Security, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
import storage
import git_backup
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


class UpdateItem(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None


class MoveItem(BaseModel):
    destination: str
    by_id: bool = False


def _serialize(obj: dict) -> dict:
    return {k: str(v) if isinstance(v, Path) else v
            for k, v in obj.items() if k != "html_content"}


# Specific sub-resource routes must be registered before the general /{path:path}
# routes so Starlette matches them before the greedy path catch-all.

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
        f"---\n{yaml.dump({'name': name, 'id': item_id})}---\n{body.content}")
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
    (item_path / "index.md").write_text(
        f"---\n{yaml.dump({'id': item_id})}---\n{content}")
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
