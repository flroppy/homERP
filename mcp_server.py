#!/usr/bin/env python3
"""
homERP MCP server — exposes inventory tools over stdio.

Configuration (environment variables):
  HOMERP_BASE_URL   Base URL of the homERP instance (default: http://localhost:80)
  HOMERP_API_KEY    API key if authentication is enabled (default: none)
"""
import base64
import json
import os
import httpx
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP

READABLE_EXTENSIONS = {".txt", ".md", ".pdf"}
WRITABLE_EXTENSIONS = {".txt", ".md"}

BASE_URL = os.environ.get("HOMERP_BASE_URL", "http://localhost:80").rstrip("/")
API_KEY = os.environ.get("HOMERP_API_KEY", "")

_INSTRUCTIONS = """
homERP is a home inventory system. Everything in it is an **item** — a named container that can
hold other items (nested arbitrarily), a markdown description, a photo, and file attachments.

## Paths
Items are identified by a slash-separated path relative to the inventory root, e.g.:
  - "" or "/" — the root (all top-level items)
  - "Living Room" — a top-level item
  - "Living Room/Shelving Unit/Shelf 2" — a deeply nested item

Paths have NO leading slash. Use an empty string "" for the root.

## Data model
browse() returns JSON like:
  {
    "id": "aB3xY7z2",        // 8-char base64 ID, unique across all items
    "name": "Shelf 2",
    "path": "Living Room/Shelving Unit/Shelf 2",
    "content": "markdown text...",
    "photo_path": "/download/...",   // null if no photo
    "children": [ { "id", "name", "path", "content", ... }, ... ],
    "attachments": [ { "name": "receipt.pdf", "path": "...", "size": 1234 }, ... ]
  }

## Workflow tips
- Use browse("") to orient yourself, then browse a specific path to see its children.
- Use search() to find items by name or content before navigating to them.
- IDs are stable even if an item is renamed or moved — prefer move_item(by_id=True) when
  referring to items that might be renamed.
""".strip()

mcp = FastMCP("homERP", instructions=_INSTRUCTIONS)

Path = Annotated[str, Field(description='Slash-separated item path, e.g. "Living Room/Box". Empty string "" for root.')]
Destination = Annotated[str, Field(description="Path or ID of the destination item (a directory that will contain the moved item).")]


def _client() -> httpx.Client:
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    return httpx.Client(base_url=BASE_URL, headers=headers, timeout=10)


def _fmt(data) -> str:
    return json.dumps(data, indent=2)


@mcp.tool(name="homerp list fields")
def list_fields() -> str:
    """Return all custom field names and their known values across the inventory. Use this to discover what categories, tags, and other metadata have been applied to items."""
    with _client() as c:
        r = c.get("/api/fields")
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool(name="homerp filter")
def filter_by_field(
    field: Annotated[str, Field(description="Custom field name to filter on, e.g. 'category'.")],
    value: Annotated[str, Field(description="Value to match (case-insensitive), e.g. 'Board Games'.")],
) -> str:
    """List all items where a custom field equals the given value, regardless of where they're stored."""
    with _client() as c:
        r = c.get("/api/filter", params={"field": field, "value": value})
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool(name="homerp tree")
def tree() -> str:
    """Return the full inventory as a nested tree (id, name, path, children). No content or attachments — use browse() for details on a specific item."""
    with _client() as c:
        r = c.get("/api/tree")
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool(name="homerp get photo")
def get_photo(path: Path) -> str:
    """Download the photo for an item, returned as base64. MCP parameters are JSON so binary must be base64-encoded."""
    with _client() as c:
        r = c.get(f"/api/items/{path}/photo")
        r.raise_for_status()
        return f"Photo (base64):\n{base64.b64encode(r.content).decode()}"


@mcp.tool(name="homerp upload photo")
def upload_photo(
    path: Path,
    image_base64: Annotated[str, Field(description="Base64-encoded image bytes. MCP parameters are JSON so binary must be base64-encoded.")],
    mime_type: Annotated[str, Field(description="Either 'image/jpeg' or 'image/png'.")] = "image/jpeg",
) -> str:
    """Set or replace the photo thumbnail for an item. MCP requires base64; use POST /api/items/{path}/photo directly for raw binary upload."""
    data = base64.b64decode(image_base64)
    ext = "png" if mime_type == "image/png" else "jpg"
    with _client() as c:
        r = c.post(
            f"/api/items/{path}/photo",
            files={"file": (f"photo.{ext}", data, mime_type)},
        )
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool(name="homerp print label")
def print_label(path: Path) -> str:
    """Print a physical barcode label for an item. Returns an error if no printer is configured on the server."""
    with _client() as c:
        r = c.post(f"/api/items/{path}/print")
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool(name="homerp browse")
def browse(path: Path = "") -> str:
    """Return an item's metadata, direct children, and attachment list as JSON."""
    with _client() as c:
        r = c.get(f"/api/items/{path}")
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool(name="homerp search")
def search(query: Annotated[str, Field(description="Name, content keywords, or an 8-char item ID.")]) -> str:
    """Fuzzy-search all items by name or content. An exact 8-char ID returns a direct match."""
    with _client() as c:
        r = c.get("/api/search", params={"query": query})
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool(name="homerp create item")
def create_item(
    name: Annotated[str, Field(description="Display name for the new item. Must be unique within its parent.")],
    parent_path: Path = "",
    content: Annotated[str, Field(description="Optional markdown description.")] = "",
    fields: Annotated[dict[str, str], Field(description="Optional custom key-value metadata, e.g. {\"category\": \"Board Games\"}.")] = {},
) -> str:
    """Create a new item under parent_path. Returns the new item's id and path."""
    with _client() as c:
        r = c.post(f"/api/items/{parent_path}", json={"name": name, "content": content, "fields": fields})
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool(name="homerp update item")
def update_item(
    path: Path,
    name: Annotated[str, Field(description="New name. Omit or pass '' to keep the current name.")] = "",
    content: Annotated[str, Field(description="New markdown content. Omit or pass '' to keep the current content.")] = "",
    fields: Annotated[dict[str, str] | None, Field(description="Custom fields to set or update. Merged with existing fields — omit to leave fields untouched, pass {} to clear all custom fields.")] = None,
) -> str:
    """Rename an item, update its markdown content, and/or set custom fields. Returns the (possibly new) path."""
    body = {}
    if name:
        body["name"] = name
    if content:
        body["content"] = content
    if fields is not None:
        body["fields"] = fields
    with _client() as c:
        r = c.patch(f"/api/items/{path}", json=body)
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool(name="homerp delete item")
def delete_item(path: Path) -> str:
    """Delete an item. Its children are promoted to the deleted item's parent location."""
    with _client() as c:
        r = c.delete(f"/api/items/{path}")
        r.raise_for_status()
        return "deleted"


@mcp.tool(name="homerp move item")
def move_item(
    path: Path,
    destination: Destination,
    by_id: Annotated[bool, Field(description="Set True if destination is an item ID rather than a path.")] = False,
) -> str:
    """Move an item into a new parent. Returns the item's new path."""
    with _client() as c:
        r = c.post(f"/api/items/{path}/move",
                   json={"destination": destination, "by_id": by_id})
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool(name="homerp read attachment")
def read_attachment(
    path: Path,
    filename: Annotated[str, Field(description="Filename including extension, e.g. 'notes.md'. Supported: .txt, .md (text), .pdf (base64).")],
) -> str:
    """Read a file attachment from an item. Text files are returned as-is; PDFs as base64."""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in READABLE_EXTENSIONS:
        return f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(READABLE_EXTENSIONS))}"
    with _client() as c:
        r = c.get(f"/api/items/{path}/attachments/{filename}")
        r.raise_for_status()
        if ext == ".pdf":
            return f"PDF content (base64):\n{base64.b64encode(r.content).decode()}"
        return r.text


@mcp.tool(name="homerp delete attachment")
def delete_attachment(
    path: Path,
    filename: Annotated[str, Field(description="Filename including extension, e.g. 'receipt.pdf'.")],
) -> str:
    """Delete a file attachment from an item."""
    with _client() as c:
        r = c.delete(f"/api/items/{path}/attachments/{filename}")
        r.raise_for_status()
        return "deleted"


@mcp.tool(name="homerp write attachment")
def write_attachment(
    path: Path,
    filename: Annotated[str, Field(description="Filename including extension. Supported: .txt, .md. Creates or overwrites.")],
    content: Annotated[str, Field(description="Text content to write.")],
) -> str:
    """Write a .txt or .md file attachment to an item, creating or overwriting it."""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in WRITABLE_EXTENSIONS:
        return f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(WRITABLE_EXTENSIONS))}"
    with _client() as c:
        r = c.post(
            f"/api/items/{path}/attachments",
            files={"file": (filename, content.encode(), "text/plain")},
        )
        r.raise_for_status()
        return _fmt(r.json())


if __name__ == "__main__":
    mcp.run()
