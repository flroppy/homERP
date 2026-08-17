import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import git_backup
import storage
from config import settings
from routers import items, barcodes, api

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())

# The only mutating route that isn't a POST/PUT/PATCH/DELETE.
_DEMO_BLOCKED_GET_PREFIX = "/delete-attachment/"


@asynccontextmanager
async def lifespan(app):
    git_backup.ensure_repo(storage.HOUSE_ROOT)
    yield

app = FastAPI(title="homERP", docs_url="/api/", redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def demo_read_only_guard(request: Request, call_next):
    if settings.demo_read_only:
        is_write = request.method in ("POST", "PUT", "PATCH", "DELETE")
        is_get_delete = (
            request.method == "GET" and request.url.path.startswith(_DEMO_BLOCKED_GET_PREFIX)
        )
        if is_write or is_get_delete:
            return JSONResponse({"detail": "Demo mode is read-only."}, status_code=403)
    return await call_next(request)


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(items.router, include_in_schema=False)
app.include_router(barcodes.router, include_in_schema=False)
app.include_router(api.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=True)
