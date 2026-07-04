import logging
from io import BytesIO
from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import storage
import barcode as barcode_mod

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/barcode/{path:path}")
async def barcode_file(path: str):
    item_path = storage.HOUSE_ROOT / path
    metadata = storage.read_index_file(item_path)
    if not metadata:
        raise HTTPException(status_code=404, detail="Item not found")
    img = barcode_mod.generate_barcode(metadata.get("id"))
    barcode_mod.send_to_printer(img)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@router.get("/barcode-with-label/{path:path}")
async def barcode_with_label(path: str):
    item_path = storage.HOUSE_ROOT / path
    metadata = storage.read_index_file(item_path)
    if not metadata:
        raise HTTPException(status_code=404, detail="Item not found")
    item_id = metadata.get("id")
    if not item_id:
        raise HTTPException(status_code=404, detail="Item ID not found")
    canvas = barcode_mod.generate_barcode_with_label(item_id, metadata.get("name"))
    barcode_mod.send_to_printer(canvas)
    buf = BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@router.post("/print_grocy")
async def print_grocy(payload: Dict[Any, Any]):
    log.info("print_grocy payload: %s", payload)
    try:
        grocycode = payload['grocycode']
        product = payload['product']
        due_date = payload.get('due_date')
        canvas = barcode_mod.generate_barcode_with_label(grocycode, product, due_date if due_date else None)
        barcode_mod.send_to_printer(canvas)
        return {"success": "true"}
    except Exception as e:
        log.exception("print_grocy failed")
        return {"success": "false", "error": str(e)}
