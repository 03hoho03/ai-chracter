"""Pillow 기반 이미지 변형.

`from PIL import ...`이 함수 안에 있는 건 프로세스 기동(재배포·재시작·크래시 복구) 비용
때문이다: Pillow는 import에만 3.7MB를 읽는데 여기 함수들은 이미지를 다루는 경로(업로드·블러·썸네일·참조 검증)에서만 불린다.
최상단으로 올리면 `assets/router.py`를 타고 모든 기동이 그 비용을 문다 — 올리지 말 것.
"""

import io
from typing import Literal

BLUR_RADIUS = 25.0
BLURRED_CONTENT_TYPE = "image/png"

THUMBNAIL_MAX_EDGE = 512
THUMBNAIL_WEBP_QUALITY = 80
THUMBNAIL_CONTENT_TYPE = "image/webp"


def generate_blurred_image(image_bytes: bytes, radius: float = BLUR_RADIUS) -> bytes:
    """CPU-bound (Pillow) — run via `run_in_threadpool`.

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


def read_image_size(image_bytes: bytes) -> tuple[int, int]:
    """(너비, 높이) 픽셀. 헤더만 읽는다. EXIF 회전은 보지 않는다 — 업로드 원본은 화면이 회전을 픽셀에
    굽고 EXIF 를 버린 WebP 로 올리고, 생성·블러 이미지는 EXIF 가 없어 이 값이 곧 화면의 가로세로다.
    그림이 아니면 Pillow 가 `OSError`(`UnidentifiedImageError`)를 낸다."""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as image:
        return image.size


def read_image_content_type(image_bytes: bytes) -> str | None:
    """Pillow 가 바이트에서 읽은 형식의 MIME 타입(`image/webp` 등). Pillow 가 MIME 을 모르는 형식이면 `None`.
    헤더만 읽는다. 그림이 아니면 `read_image_size` 처럼 `OSError` 를 낸다."""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as image:
        return image.get_format_mimetype()


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


# 집 PC 계약 v4 의 참조 이미지 한도. 인코딩 길이는 base64 문자 수로 센다(서버가 받는 문자열 기준).
REFERENCE_IMAGE_MAX_ENCODED_CHARS = 8_000_000
REFERENCE_IMAGE_MIN_EDGE = 64
REFERENCE_IMAGE_MAX_EDGE = 4096
# 지금 생성기는 WebP 를 주지만 그 전 생성기가 남긴 생성 이미지(PNG·JPEG)도 참조로 고를 수 있다.
REFERENCE_IMAGE_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})

ReferenceImageRejection = Literal["too_large", "undecodable", "unsupported_format", "resolution_out_of_range"]


class ReferenceImageRejectedError(Exception):
    """참조 이미지가 계약 한도를 벗어났다. `reason` 은 위반 종류만 담는다 — 로그에 그대로 남기므로
    바이트·저장 키 같은 식별 정보를 싣지 않는다."""

    def __init__(self, reason: ReferenceImageRejection) -> None:
        self.reason = reason
        super().__init__(f"reference image rejected: {reason}")


def validate_reference_image(image_bytes: bytes) -> None:
    """CPU-bound (Pillow) — run via `run_in_threadpool`.

    집 PC 에 참조로 보내기 전에 계약 한도를 확인한다. 헤더만 읽고 고치지 않는다(리사이즈·재인코딩
    없음) — 사용자가 고를 수 있는 참조가 이 서비스의 생성 이미지뿐이라 정상 경로에서는 위반이 나오지
    않고, 나오면 고칠 대상이 아니라 알아야 할 결함이다."""
    # base64 는 3바이트마다 4문자이고, 남는 1~2바이트도 패딩을 붙여 4문자가 된다.
    if 4 * ((len(image_bytes) + 2) // 3) > REFERENCE_IMAGE_MAX_ENCODED_CHARS:
        raise ReferenceImageRejectedError("too_large")

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image_format = image.format
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ReferenceImageRejectedError("undecodable") from exc

    if image_format not in REFERENCE_IMAGE_FORMATS:
        raise ReferenceImageRejectedError("unsupported_format")
    if not (
        REFERENCE_IMAGE_MIN_EDGE <= width <= REFERENCE_IMAGE_MAX_EDGE
        and REFERENCE_IMAGE_MIN_EDGE <= height <= REFERENCE_IMAGE_MAX_EDGE
    ):
        raise ReferenceImageRejectedError("resolution_out_of_range")
