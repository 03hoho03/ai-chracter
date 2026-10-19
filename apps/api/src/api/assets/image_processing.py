"""Pillow 기반 이미지 변형.

`from PIL import ...`이 함수 안에 있는 건 프로세스 기동(재배포·재시작·크래시 복구) 비용
때문이다: Pillow는 import에만 3.7MB를 읽는데 여기 함수들은 이미지를 다루는 경로(업로드·블러·썸네일·참조 검증)에서만 불린다.
최상단으로 올리면 `assets/router.py`를 타고 모든 기동이 그 비용을 문다 — 올리지 말 것.
"""

import asyncio
import io
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Literal, ParamSpec, TypeVar

from starlette.concurrency import run_in_threadpool

from api.core.config import settings
from api.core.s3 import build_display_key, build_frame_sheet_key, build_thumbnail_key

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

_P = ParamSpec("_P")
_T = TypeVar("_T")

BLUR_RADIUS = 25.0
BLURRED_CONTENT_TYPE = "image/png"

THUMBNAIL_MAX_EDGE = 512
THUMBNAIL_WEBP_QUALITY = 80
# 썸네일과 표시용 변형 둘 다 WebP 라 같은 값을 쓴다.
THUMBNAIL_CONTENT_TYPE = "image/webp"

# 표시용 변형: 상세 화면 히어로처럼 썸네일보다 크게 그리는 자리에 원본 대신 보낸다. 1024 는 데스크톱 상세 모달
# (스토리 256×384 CSS px)을 2배 밀도 화면에서 덮고, 화면이 대표 이미지 업로드 전에 줄이는 긴 변 상한
# (`apps/web/src/shared/api/asset/uploadAsset.ts` 의 `content-thumbnail`)과 같아 업로드한 그림보다 작아지지 않는다.
DISPLAY_MAX_EDGE = 1024
# 썸네일과 같은 q80 — 운영에서 이미 쓰는 값이고, 표시용에만 다른 값을 고를 화질 비교 측정은 없다.
DISPLAY_WEBP_QUALITY = THUMBNAIL_WEBP_QUALITY

# 디코드할 그림의 픽셀 수 상한(3000×3000). 정상 입력의 최대는 화면이 업로드 전에 줄이는 긴 변 2048 의 정사각
# (약 4.19M)이고 생성 이미지는 긴 변 1344 라, 두 배 넘게 남는다. 바이트 상한만으로는 못 막는다 — 단색 PNG 는
# 수십 KB 로 수천만 픽셀을 담고, 디코드는 픽셀마다 RGBA 4바이트에 블러·축소 복사본까지 메모리를 쓴다.
# Pillow 자체 검사(`MAX_IMAGE_PIXELS`)는 약 8,950만 픽셀 이하에는 반응하지 않고, 그 초과~2배(약 1.79억)에서는 경고만,
# 2배를 넘어야 오류(`DecompressionBombError`)를 낸다.
# ⚠️ 호출 시점에 모듈 전역으로 읽는다(테스트가 `monkeypatch.setattr` 로 낮춘다).
MAX_DECODE_PIXELS = 9_000_000

# 움직이는 그림의 프레임 수 × 프레임 픽셀 상한. 프레임 모음은 고른 프레임까지 앞 프레임을 차례로 풀어야 닿으므로 일은
# 이 총량에 비례한다(메모리는 한 프레임과 모음 한 장만 든다). 업로드 상한 5MB 안의 현실적인 움짤(600×800, 60프레임
# = 약 2,900만)의 세 배쯤이다. 5MB 로도 단색 프레임은 수천 장을 담을 수 있어 바이트 상한만으로는 못 막는다.
# ⚠️ 호출 시점에 모듈 전역으로 읽는다(테스트가 `monkeypatch.setattr` 로 낮춘다).
MAX_ANIMATED_DECODE_PIXELS = 100_000_000

# 프레임 모음: 처음과 마지막을 포함해 고르게 뽑는 프레임 수와 모음 한 장의 긴 변. 9장 3×3 이면 1024 에서 칸 하나가
# 약 340px 다. 심사는 움직이는 그림 하나에 이 한 장을 싣는다 — 이미지 목록 줄과 실린 그림이 하나씩 짝을 이룬다.
FRAME_SHEET_SLOTS = 9
FRAME_SHEET_MAX_EDGE = 1024
FRAME_SHEET_WEBP_QUALITY = THUMBNAIL_WEBP_QUALITY

# 디코드·블러·변형 생성을 한 번에 몇 건까지 돌릴지(프로세스 전역). 픽셀 상한은 한 장의 메모리만 묶고, 동시 요청
# 수(스레드풀 40, 미디어 북 블러 8)가 곱해지는 것은 못 막는다. 값은 env `IMAGE_DECODE_CONCURRENCY` 로 정한다 — 워커를
# 늘리면 워커 수만큼 곱해지므로 VM 메모리에 맞춰 줄인다. import 시점에 한 번 읽는다(세마포어를 그때 만든다).
IMAGE_WORK_CONCURRENCY = settings.image_decode_concurrency
# asyncio 세마포어라 기다리는 요청은 스레드풀 칸을 잡지 않는다 — 스레드 안에서 기다리게 하면 기다리는 작업이
# 스레드풀을 채워, 이미지와 무관한 `run_in_threadpool` 호출(저장소 왕복·비밀번호 해시)까지 줄을 선다.
# 모듈 전역이라 처음 기다림이 생긴 이벤트 루프에 묶인다 — 앱은 루프 하나로 돌고, 테스트도 세션 루프 하나다.
_image_work_slots = asyncio.Semaphore(IMAGE_WORK_CONCURRENCY)


class ImageTooLargeError(ValueError):
    """디코드하기 전에 픽셀 수가 `MAX_DECODE_PIXELS` 를 넘었다. `ValueError` 하위라 "그림으로 풀지 못했다"를 잡는
    기존 `except (OSError, ValueError)` 들이 그대로 받는다 — 업로드 완료처럼 원인을 따로 알리려는 곳만 먼저 잡는다.
    `actual_pixels` 는 Pillow 가 크기를 알려 주기 전에 스스로 거부했을 때(약 1.8억 픽셀 초과) `None` 이다.
    `max_pixels` 는 검사에 실제로 쓴 상한이다 — 호출자가 상수를 따로 import 해 알리면 검사와 어긋날 수 있다. 움직이는
    그림의 총량 검사는 그 상한(`MAX_ANIMATED_DECODE_PIXELS`)을 넘긴다."""

    def __init__(self, actual_pixels: int | None, max_pixels: int | None = None) -> None:
        self.actual_pixels = actual_pixels
        self.max_pixels = MAX_DECODE_PIXELS if max_pixels is None else max_pixels
        super().__init__(f"image has {actual_pixels} pixels, limit is {self.max_pixels}")


async def run_image_work(func: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
    """디코드하는 함수(블러·변형 생성)를 `IMAGE_WORK_CONCURRENCY` 한도 안에서 스레드풀로 돌린다. 헤더만 읽는 함수는
    메모리를 거의 쓰지 않아 이 한도 밖에서 그대로 `run_in_threadpool` 로 부른다. 안에서 다시 이 함수를 부르지
    않는다(세마포어는 재진입하지 않는다)."""
    async with _image_work_slots:
        return await run_in_threadpool(func, *args, **kwargs)


@contextmanager
def _open_for_decode(image_bytes: bytes) -> Iterator["PILImage"]:
    """헤더만 읽어 픽셀 수를 확인한 뒤 연 그림을 넘긴다. `Image.open` 은 픽셀을 풀지 않으므로 이 검사는 디코드
    (`load()`) 전이다."""
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(image_bytes))
    except Image.DecompressionBombError as exc:
        # `Exception` 직속이라 `OSError`·`ValueError` 를 잡는 호출자들을 빠져나가 500 이 된다 — 같은 오류로 바꾼다.
        raise ImageTooLargeError(None) from exc
    with image:
        width, height = image.size
        if width * height > MAX_DECODE_PIXELS:
            raise ImageTooLargeError(width * height)
        yield image


def generate_blurred_image(image_bytes: bytes, radius: float = BLUR_RADIUS) -> bytes:
    """CPU-bound (Pillow) — run via `run_image_work`.

    Always normalizes to RGBA/PNG regardless of the source format, so the blur
    filter (which chokes on palette-mode GIFs/etc.) and the output encoding both
    have one predictable mode to deal with.
    """
    from PIL import ImageFilter

    with _open_for_decode(image_bytes) as original:
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


def read_frame_count(image_bytes: bytes) -> int:
    """움직이는 그림의 프레임 수. 정지 그림은 1 이다. 픽셀은 풀지 않고 프레임 데이터를 건너뛰며 센다 — 100프레임 GIF
    에서 전체 디코드의 약 1/10 이 든다(로컬 측정 0.13초 대 1.24초)."""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as image:
        return int(getattr(image, "n_frames", 1))


def generate_thumbnail(image_bytes: bytes) -> bytes:
    """CPU-bound (Pillow) — run via `run_image_work`.

    Shrinks the long edge to THUMBNAIL_MAX_EDGE (never upscales) and encodes as WebP."""
    return _shrink_to_webp(image_bytes, THUMBNAIL_MAX_EDGE, THUMBNAIL_WEBP_QUALITY)


def generate_display_image(image_bytes: bytes) -> bytes:
    """CPU-bound (Pillow) — run via `run_image_work`.

    `generate_thumbnail` 과 같은 규칙으로 긴 변을 DISPLAY_MAX_EDGE 로 줄인다. 원본이 더 작으면 원본 크기 그대로다."""
    return _shrink_to_webp(image_bytes, DISPLAY_MAX_EDGE, DISPLAY_WEBP_QUALITY)


def generate_variants(storage_key: str, image_bytes: bytes) -> list[tuple[str, bytes]]:
    """CPU-bound (Pillow) — run via `run_image_work`.

    원본 곁에 둘 변형 전부를 `(저장 키, WebP 바이트)` 로 만든다. 썸네일·표시용은 늘(움직이는 그림이면 첫 프레임),
    프레임 모음은 움직이는 그림에만 만든다. 응답이 썸네일·표시용 키를 존재 확인 없이 유도하므로, 자산을 만드는 경로는
    이 목록을 전부 올린 뒤에만 READY 로 둔다. 키 순서는 `build_variant_keys`(지우는 쪽) 와 같다."""
    variants = [
        (build_thumbnail_key(storage_key), generate_thumbnail(image_bytes)),
        (build_display_key(storage_key), generate_display_image(image_bytes)),
    ]
    frame_sheet = _generate_frame_sheet(image_bytes)
    if frame_sheet is not None:
        variants.append((build_frame_sheet_key(storage_key), frame_sheet))
    return variants


def _generate_frame_sheet(image_bytes: bytes) -> bytes | None:
    """움직이는 그림에서 처음과 마지막을 포함해 프레임을 고르게 `FRAME_SHEET_SLOTS` 장 뽑아 격자 한 장에 붙인다.
    정지 그림이면 `None`. 격자는 정사각에 가깝게 열을 먼저 채우고(3장 2×2, 9장 3×3), 비는 칸은 투명이다. 칸은 프레임
    비율 그대로 줄이고 늘리지 않는다."""
    from PIL import Image

    with _open_for_decode(image_bytes) as original:
        frame_count = int(getattr(original, "n_frames", 1))
        if frame_count <= 1:
            return None
        width, height = original.size
        if frame_count * width * height > MAX_ANIMATED_DECODE_PIXELS:
            raise ImageTooLargeError(frame_count * width * height, max_pixels=MAX_ANIMATED_DECODE_PIXELS)

        slots = min(FRAME_SHEET_SLOTS, frame_count)
        indices = [round(slot * (frame_count - 1) / (slots - 1)) for slot in range(slots)]
        columns = math.ceil(math.sqrt(slots))
        rows = math.ceil(slots / columns)
        scale = min(1.0, FRAME_SHEET_MAX_EDGE / (columns * width), FRAME_SHEET_MAX_EDGE / (rows * height))
        tile_width, tile_height = max(1, round(width * scale)), max(1, round(height * scale))

        sheet = Image.new("RGBA", (columns * tile_width, rows * tile_height), (0, 0, 0, 0))
        for slot, index in enumerate(indices):
            original.seek(index)
            frame = original.convert("RGBA").resize((tile_width, tile_height))
            row, column = divmod(slot, columns)
            sheet.paste(frame, (column * tile_width, row * tile_height))

    output = io.BytesIO()
    sheet.save(output, format="WEBP", quality=FRAME_SHEET_WEBP_QUALITY)
    return output.getvalue()


def _shrink_to_webp(image_bytes: bytes, max_edge: int, quality: int) -> bytes:
    """Like `generate_blurred_image`, always normalizes to RGBA first so palette-mode sources and the output
    encoding have one predictable mode. `Image.thumbnail` only ever shrinks, so small sources keep their size."""
    with _open_for_decode(image_bytes) as original:
        original.load()
        shrunk = original.convert("RGBA")
        shrunk.thumbnail((max_edge, max_edge))

    output = io.BytesIO()
    shrunk.save(output, format="WEBP", quality=quality)
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
