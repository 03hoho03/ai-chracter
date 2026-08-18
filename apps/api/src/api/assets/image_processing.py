import io

from PIL import Image, ImageFilter

BLUR_RADIUS = 25.0
BLURRED_CONTENT_TYPE = "image/png"

THUMBNAIL_MAX_EDGE = 512
THUMBNAIL_WEBP_QUALITY = 80
THUMBNAIL_CONTENT_TYPE = "image/webp"


def generate_blurred_image(image_bytes: bytes, radius: float = BLUR_RADIUS) -> bytes:
    """techspec-backend-media.md §2. CPU-bound (Pillow) — run via `run_in_threadpool`.

    Always normalizes to RGBA/PNG regardless of the source format, so the blur
    filter (which chokes on palette-mode GIFs/etc.) and the output encoding both
    have one predictable mode to deal with.
    """
    with Image.open(io.BytesIO(image_bytes)) as original:
        original.load()
        blurred = original.convert("RGBA").filter(ImageFilter.GaussianBlur(radius=radius))

    output = io.BytesIO()
    blurred.save(output, format="PNG")
    return output.getvalue()


def generate_thumbnail(image_bytes: bytes) -> bytes:
    """CPU-bound (Pillow) — run via `run_in_threadpool`.

    Shrinks the long edge to THUMBNAIL_MAX_EDGE (never upscales) and encodes as
    WebP. Like `generate_blurred_image`, always normalizes to RGBA first so
    palette-mode sources and the output encoding have one predictable mode.
    """
    with Image.open(io.BytesIO(image_bytes)) as original:
        original.load()
        thumbnail = original.convert("RGBA")
        thumbnail.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE))

    output = io.BytesIO()
    thumbnail.save(output, format="WEBP", quality=THUMBNAIL_WEBP_QUALITY)
    return output.getvalue()
