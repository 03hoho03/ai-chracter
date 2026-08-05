"""시드 이미지의 S3 업로드와 `assets` 행 upsert.

moto 는 인메모리라 컨테이너를 재생성하면 업로드된 객체가 전부 사라진다 — Postgres 는
볼륨으로 살아남으니 DB 행만 남고 썸네일이 전부 깨진 상태가 된다. 그래서 시드는 DB 상태와
무관하게 이미지를 **매번** 다시 올린다. `Asset.id` 와 S3 키는 slug 에서 파생한 고정값이라
몇 번을 돌려도 같은 행·같은 객체를 덮어쓴다.

진짜 이미지(`images/{slug}.png`)는 gitignore 라 새 머신에는 없다. 그럴 땐 장르 색이 다른
절차적 목업 PNG 로 대체하고 경고 한 줄만 남긴다 — 이미지가 없다고 시드가 실패하면 안 된다.
진짜 이미지는 `scripts/generate_seed_images.py` 로 다시 뽑는다.
"""

import colorsys
import hashlib
import io
import uuid
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.s3 import build_object_key, upload_object
from api.db.models.media import Asset, AssetKind, AssetStatus

from .ids import SEED_AUTHOR_USER_ID, seed_uuid

IMAGES_DIR = Path(__file__).parent / "images"
CONTENT_TYPE = "image/png"
SIZE = (480, 720)  # seed_dev.py 의 기존 placeholder 와 같은 규격

# 장르별 색상(HSV 색상환 각도). 키는 마이그레이션 91a008760f4a 가 시드한 장르명 그대로다.
GENRE_HUES: dict[str, float] = {
    "공포": 0,
    "무협·액션": 25,
    "개그·코미디": 55,
    "일상": 90,
    "학원": 125,
    "힐링": 160,
    "SF": 195,
    "미스터리·스릴러": 235,
    "판타지": 280,
    "로맨스": 335,
}
# 장르를 모르는 이미지(캐릭터 상황 컷 등)는 색 없이 회색조로 둔다.
UNKNOWN_HUE = 250.0
UNKNOWN_SATURATION = 0.04

# DESIGN.md 다크 팔레트(배경 oklch 0.16 / 카드 0.21 / 보더 0.30) 위에 얹히는 톤이라
# 저채도·저광량으로 묶는다. 명도 천장 0.36 은 최대 채널 92/255 — 순백은커녕 밝은 톤 자체가
# 나올 수 없다. 색은 콘텐츠(썸네일)에만 존재한다는 규칙 안이라 채도는 살짝 허용한다.
SATURATION = 0.22
TOP_VALUE_RANGE = (0.22, 0.36)  # 바닥은 배경(oklch 0.16)보다 확실히 밝아야 카드로 읽힌다
BOTTOM_VALUE_RATIO = 0.45  # 아래로 갈수록 어두워지는 세로 그라데이션
HUE_JITTER = 24.0  # 같은 장르 안에서 색 계열은 유지하되 슬롯끼리 조금 갈라놓는다

# 명도는 slug 해시라 같은 장르 슬롯끼리 우연히 붙을 수 있다(사전 조정이 불가능하다). 그래서
# slug 가 위치와 기울기를 정하는 사선 띠를 하나 더 얹는다 — 명도가 붙은 두 카드도 띠에서
# 갈라진다. 띠는 바탕보다 어둡게 깔아 명도 천장(그라데이션 상단)을 건드리지 않는다.
BAND_CENTER_RANGE = (0.12, 0.88)  # 세로 위치 비율
BAND_HEIGHT_RATIO = 0.16
BAND_SLANT_RATIO = 0.22
BAND_VALUE_RATIO = 0.62


def mock_thumbnail(slug: str, genre_name: str | None = None) -> bytes:
    """장르가 색을, slug 가 명도와 띠 위치를 정하는 절차적 목업 (외부 API 호출 없음).

    같은 장르의 슬롯끼리는 명도가 다르고, 명도가 우연히 붙어도 사선 띠 위치가 달라
    홈 목록에서 카드가 서로 구분된다.
    """
    base_hue = GENRE_HUES.get(genre_name or "", UNKNOWN_HUE)
    saturation = SATURATION if (genre_name or "") in GENRE_HUES else UNKNOWN_SATURATION
    low, high = TOP_VALUE_RANGE
    top_value = low + (high - low) * _unit_hash(slug, "value")
    bottom_value = top_value * BOTTOM_VALUE_RATIO
    hue = (base_hue + (_unit_hash(slug, "hue") - 0.5) * HUE_JITTER) % 360

    width, height = SIZE
    image = Image.new("RGB", SIZE)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        value = top_value + (bottom_value - top_value) * (y / (height - 1))
        draw.line([(0, y), (width, y)], fill=_rgb(hue, saturation, value))

    band_top = band_center(slug) * height
    band_bottom = band_top + height * BAND_HEIGHT_RATIO
    slant = height * BAND_SLANT_RATIO * band_slant_sign(slug)
    draw.polygon(
        [
            (0, band_top),
            (width, band_top - slant),
            (width, band_bottom - slant),
            (0, band_bottom),
        ],
        fill=_rgb(hue, saturation, top_value * BAND_VALUE_RATIO),
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def band_center(slug: str) -> float:
    """목업 사선 띠의 세로 위치 비율 — 같은 장르 카드가 갈라지는 두 번째 축."""
    low, high = BAND_CENTER_RANGE
    return low + (high - low) * _unit_hash(slug, "band")


def band_slant_sign(slug: str) -> int:
    """띠가 오른쪽으로 올라가는지(+1) 내려가는지(-1) — 세 번째 축."""
    return 1 if _unit_hash(slug, "slant") < 0.5 else -1


def read_image(slug: str, genre_name: str | None = None) -> bytes:
    """`images/{slug}.png` 의 바이트, 없으면 경고 한 줄과 함께 목업."""
    path = IMAGES_DIR / f"{slug}.png"
    if path.is_file():
        return path.read_bytes()
    print(
        f"  ! 시드 이미지 없음({path.name}) — 목업 썸네일로 대체."
        " 실제 이미지는 scripts/generate_seed_images.py 로 생성한다"
    )
    return mock_thumbnail(slug, genre_name)


async def ensure_asset(
    session: AsyncSession,
    slug: str,
    kind: AssetKind,
    genre_name: str | None = None,
    *,
    data: bytes | None = None,
) -> uuid.UUID:
    """이미지를 S3 에 올리고 `Asset` 행을 upsert 한 뒤 asset id 를 돌려준다.

    `data` 를 주면 파일/목업 대신 그 바이트를 올린다 — 원본에서 파생한 블러본처럼 디스크에
    없는 이미지를 위한 통로다.

    호출 전에 작가 `User` 행이 flush 돼 있어야 한다(`assets.owner_user_id` FK). 업로드가
    실패해도(moto 미기동 등) 경고만 남기고 행은 그대로 넣는다 — 썸네일만 깨지고 나머지 시드는
    계속돼야 한다.
    """
    asset_id = seed_uuid("asset", slug, kind.value)
    storage_key = build_object_key("seed", asset_id, CONTENT_TYPE)
    body = data if data is not None else read_image(slug, genre_name)

    try:
        upload_object(storage_key, body, CONTENT_TYPE)
    except Exception as exc:  # noqa: BLE001 - moto 미기동 등 어떤 실패든 시드 자체는 계속
        print(f"  ! 이미지 업로드 건너뜀({slug}, {exc!r}) — moto 기동 후 재시드하면 채워짐")

    await session.merge(
        Asset(
            id=asset_id,
            owner_user_id=SEED_AUTHOR_USER_ID,
            storage_key=storage_key,
            kind=kind,
            status=AssetStatus.READY,
        )
    )
    return asset_id


def _unit_hash(slug: str, axis: str) -> float:
    """slug 를 0.0~1.0 으로. 내장 `hash()` 는 프로세스마다 소금이 달라 쓸 수 없다."""
    digest = hashlib.sha256(f"{slug}:{axis}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


def _rgb(hue: float, saturation: float, value: float) -> tuple[int, int, int]:
    red, green, blue = colorsys.hsv_to_rgb(hue / 360.0, saturation, value)
    return round(red * 255), round(green * 255), round(blue * 255)
