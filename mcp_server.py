#!/usr/bin/env python3
"""
homERP MCP server — exposes inventory tools over stdio.

Configuration (environment variables):
  HOMERP_BASE_URL   Base URL of the homERP instance (default: http://localhost:80)
  HOMERP_API_KEY    API key if authentication is enabled (default: none)
"""
import json
import os
import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("HOMERP_BASE_URL", "http://localhost:80").rstrip("/")
API_KEY = os.environ.get("HOMERP_API_KEY", "")

mcp = FastMCP("homERP")


def _client() -> httpx.Client:
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    return httpx.Client(base_url=BASE_URL, headers=headers, timeout=10)


def _fmt(data) -> str:
    return json.dumps(data, indent=2)


@mcp.tool()
def browse(path: str = "") -> str:
    """Get an item and its direct children and attachments. Use path='' for the root."""
    with _client() as c:
        r = c.get(f"/api/items/{path}")
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool()
def search(query: str) -> str:
    """Search for items by name, content, or ID. Returns fuzzy matches or a direct ID hit."""
    with _client() as c:
        r = c.get("/api/search", params={"query": query})
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool()
def create_item(name: str, parent_path: str = "", content: str = "") -> str:
    """Create a new item. parent_path='' creates at root. Returns the new item's id and path."""
    with _client() as c:
        r = c.post(f"/api/items/{parent_path}", json={"name": name, "content": content})
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool()
def update_item(path: str, name: str = "", content: str = "") -> str:
    """Update an item's name and/or markdown content. Omit a field to leave it unchanged."""
    body = {}
    if name:
        body["name"] = name
    if content:
        body["content"] = content
    with _client() as c:
        r = c.patch(f"/api/items/{path}", json=body)
        r.raise_for_status()
        return _fmt(r.json())


@mcp.tool()
def delete_item(path: str) -> str:
    """Delete an item. Any children are promoted to the parent location."""
    with _client() as c:
        r = c.delete(f"/api/items/{path}")
        r.raise_for_status()
        return "deleted"


@mcp.tool()
def move_item(path: str, destination: str, by_id: bool = False) -> str:
    """Move an item to a new parent. destination is a path or item ID (set by_id=True for ID)."""
    with _client() as c:
        r = c.post(f"/api/items/{path}/move",
                   json={"destination": destination, "by_id": by_id})
        r.raise_for_status()
        return _fmt(r.json())


if __name__ == "__main__":
    mcp.run()
