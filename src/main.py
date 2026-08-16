import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import git_backup
import storage
from routers import items, barcodes, api

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())

@asynccontextmanager
async def lifespan(app):
    git_backup.ensure_repo(storage.HOUSE_ROOT)
    yield

app = FastAPI(title="homERP", docs_url="/api/", redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(items.router, include_in_schema=False)
app.include_router(barcodes.router, include_in_schema=False)
app.include_router(api.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=True)
