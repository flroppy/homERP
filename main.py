import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import git_backup
import storage
from routers import items, barcodes

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app):
    git_backup.ensure_repo(storage.HOUSE_ROOT)
    yield

app = FastAPI(title="House Inventory App", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(items.router)
app.include_router(barcodes.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=True)
