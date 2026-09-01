"""Pillow 기반 이미지 변형.

`from PIL import ...`이 함수 안에 있는 건 콜드스타트 때문이다: Pillow는 import에만
3.7MB를 읽는데(Cloud Run은 이미지를 lazy loading으로 스트리밍해서 이 바이트가 그대로
기동 지연이 된다) 여기 두 함수는 업로드/블러 경로에서만 불린다. 최상단으로 올리면
`assets/router.py`를 타고 모든 콜드스타트가 그 비용을 문다 — 올리지 말 것.
"""

import io

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
    from PIL import Image, ImageFilter

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
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as original:
        original.load()
        thumbnail = original.convert("RGBA")
        thumbnail.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE))

    output = io.BytesIO()
    thumbnail.save(output, format="WEBP", quality=THUMBNAIL_WEBP_QUALITY)
    return output.getvalue()
