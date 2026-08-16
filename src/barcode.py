import logging
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from pylibdmtx.pylibdmtx import encode
from brother_ql.labels import ALL_LABELS, Color
from brother_ql import BrotherQLRaster, create_label
from brother_ql.backends import guess_backend, backend_factory
from config import settings

log = logging.getLogger(__name__)

_printer_backend_class = None
_label_spec = None


def get_printer_backend():
    global _printer_backend_class, _label_spec
    if _printer_backend_class is None:
        log.info("Initializing printer backend for %s", settings.barcode_printer_address)
        selected = guess_backend(settings.barcode_printer_address)
        _printer_backend_class = backend_factory(selected)['backend_class']
        _label_spec = next(x for x in ALL_LABELS if x.identifier == settings.barcode_printer_tape)
    return _printer_backend_class, _label_spec


def generate_barcode(item_id):
    encoded = encode(item_id.encode('utf8'))
    barcode_img = Image.frombytes('RGB', (encoded.width, encoded.height), encoded.pixels)
    scale_factor = settings.barcode_rendered_height / barcode_img.height
    barcode_width = int(barcode_img.width * scale_factor)
    return barcode_img.resize(
        (barcode_width, settings.barcode_rendered_height), resample=Image.Resampling.NEAREST)


def generate_barcode_with_label(item_id, item_name, due_date: str = None):
    barcode_img = generate_barcode(item_id)

    font_path = str(Path(__file__).parent / "roboto.ttf")
    font = ImageFont.truetype(font_path, size=settings.barcode_rendered_height // 2)
    font_dd = ImageFont.truetype(font_path, size=settings.barcode_rendered_height // 3)

    scale_factor = settings.barcode_rendered_height / barcode_img.height
    barcode_img = barcode_img.resize(
        (int(barcode_img.width * scale_factor), settings.barcode_rendered_height))

    draw = ImageDraw.Draw(Image.new('RGB', (100, 100)))
    text_bbox = draw.textbbox((0, 0), item_name, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    if due_date:
        dd_bbox = draw.textbbox((0, 0), due_date, font=font_dd)
        text_width = max(text_width, dd_bbox[2] - dd_bbox[0])

    canvas = Image.new(
        'RGB',
        (barcode_img.width + text_width + 10, settings.barcode_rendered_height),
        color=(255, 255, 255),
    )
    canvas.paste(barcode_img, (0, 0))
    draw = ImageDraw.Draw(canvas)

    if not due_date:
        draw.text(
            (barcode_img.width, (barcode_img.height - text_height) // 2),
            item_name, fill="black", font=font,
        )
    else:
        draw.text((barcode_img.width, 0), item_name, fill="black", font=font)
        draw.text((barcode_img.width, barcode_img.height // 2), due_date, fill="black", font=font_dd)

    return canvas.transpose(Image.ROTATE_90)


def send_to_printer(image: Image):
    log.info("Sending label to printer %s", settings.barcode_printer_address)
    try:
        backend_class, label_spec = get_printer_backend()
        bql = BrotherQLRaster(settings.barcode_printer_model)
        create_label(bql, image, settings.barcode_printer_tape,
                     red=label_spec.color == Color.BLACK_RED_WHITE)
        be = backend_class(settings.barcode_printer_address)
        be.write(bql.data)
        del be
        log.info("Label sent successfully")
    except Exception:
        log.exception("Failed to send label to printer")
