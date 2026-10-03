"""버킷의 변형 상태를 감사한다 — 절감량 실측 + "READY 자산엔 항상 변형(썸네일·표시용)이 있다" 불변식 검증.

`backfill_thumbnails.py`가 변형을 *만드는* 쪽이라면 이 스크립트는 *확인하는* 쪽이다. 배포 전후로
돌려 (1) 원본 대비 실제로 얼마나 줄었는지, (2) 응답을 변형 키로 서명해도 404 나는 자산이
없는지를 본다. 읽기 전용이라 언제 돌려도 안전하다.

    # 로컬 (docker dev 스택의 postgres/moto)
    cd apps/api && uv run --env-file .env python scripts/verify_thumbnails.py

    # 프로덕션 (Neon + R2, 시크릿을 디스크에 안 남긴다)
    cd apps/api && env DATABASE_URL=… S3_ENDPOINT_URL=… S3_BUCKET_NAME=… \
        AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… AWS_REGION=auto \
        uv run python scripts/verify_thumbnails.py

버킷에는 있지만 DB에 행이 없는 오브젝트(실패한 생성 잡의 잔여물 등)는 썸네일이 없어도 정상이다 —
앱은 `Asset.storage_key`로만 서빙하므로 절대 참조되지 않는다. 그래서 불변식은 버킷이 아니라
**DB의 READY 자산**을 기준으로 판정한다. 종료 코드: 0 = 충족 · 1 = 원본은 있는데 변형이 빠진 자산이 있음(백필로
고쳐진다) · 2 = 빠진 것이 원본까지 없는 자산뿐(백필로 안 고쳐진다 — 목록을 출력한다).
"""

import argparse
import io
import os
import sys

# boto3(api.core.s3 모듈 전역 클라이언트)는 자격증명이 "존재"해야 하고 moto 엔드포인트를
# 알아야 한다. `--env-file .env` 로 실행하면 이미 채워져 있고, 아니면 여기서 기본값.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:5001")

import asyncio

from PIL import Image
from sqlalchemy import select

from api.core.config import settings
from api.core.s3 import build_display_key, build_thumbnail_key, build_variant_keys, download_object, s3_client
from api.db.models.media import Asset, AssetStatus
from api.db.session import async_session_factory

VARIANT_SUFFIXES = ("_thumb.webp", "_display.webp")


async def _load_ready_assets() -> list[Asset]:
    async with async_session_factory() as session:
        result = await session.scalars(
            select(Asset).where(Asset.status == AssetStatus.READY).order_by(Asset.created_at)
        )
        return list(result.all())


def _list_object_sizes() -> dict[str, int]:
    """버킷 전체의 `키 -> 바이트`. list 응답의 Size를 쓰므로 오브젝트를 내려받지 않는다."""
    sizes: dict[str, int] = {}
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket_name, Prefix="assets/"):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if key is not None:
                sizes[key] = obj.get("Size", 0)
    return sizes


def _describe_dimensions(key: str) -> str:
    """'가로x세로 포맷' — 디코드 실패는 진단 문자열로 흡수한다(감사용 출력이라 죽지 않는다)."""
    try:
        with Image.open(io.BytesIO(download_object(key))) as image:
            return f"{image.width}x{image.height} {image.format}"
    except Exception as exc:
        return f"<decode failed: {type(exc).__name__}>"


def main() -> int:
    args = _parse_args()
    sizes = _list_object_sizes()
    assets = asyncio.run(_load_ready_assets())

    target = settings.s3_endpoint_url or "AWS S3 (기본 엔드포인트)"
    print(f"대상: {target} / 버킷 {settings.s3_bucket_name}")
    variants = {key for key in sizes if key.endswith(VARIANT_SUFFIXES)}
    print(f"오브젝트 {len(sizes)}건 (변형 {len(variants)}건) / DB READY 자산 {len(assets)}건\n")

    missing: list[str] = []
    # 원본까지 없는 자산은 백필로도 못 채운다 — 따로 세어 판정을 가른다(DEPLOY.md 의 이미지 변형 백필 절).
    missing_originals: list[str] = []
    total_original = 0
    total_thumbnail = 0
    total_display = 0

    for asset in assets:
        if any(key not in sizes for key in build_variant_keys(asset.storage_key)):
            (missing if asset.storage_key in sizes else missing_originals).append(asset.storage_key)
            continue
        thumbnail_key = build_thumbnail_key(asset.storage_key)
        display_key = build_display_key(asset.storage_key)
        display_bytes = sizes[display_key]
        total_display += display_bytes

        original_bytes = sizes.get(asset.storage_key, 0)
        thumbnail_bytes = sizes[thumbnail_key]
        total_original += original_bytes
        total_thumbnail += thumbnail_bytes

        if args.verbose:
            saved = 100 - thumbnail_bytes * 100 // max(original_bytes, 1)
            dimensions = (
                f"{_describe_dimensions(asset.storage_key)} → {_describe_dimensions(thumbnail_key)}"
                f" / {_describe_dimensions(display_key)}"
            )
            print(
                f"  {original_bytes / 1024:8.0f}K → {thumbnail_bytes / 1024:6.0f}K / {display_bytes / 1024:6.0f}K"
                f"  -{saved:2d}%  {dimensions}  {asset.storage_key}"
            )

    if total_original:
        ratio = total_thumbnail * 100 // total_original
        print(
            f"썸네일 보유 자산 합계: {total_original / 1024 / 1024:.1f}MB"
            f" → {total_thumbnail / 1024 / 1024:.2f}MB ({ratio}%)"
        )
        print(
            f"표시용 변형 합계: {total_display / 1024 / 1024:.2f}MB ({total_display * 100 // total_original}%)"
        )

    orphans = len([key for key in sizes if key not in variants]) - len(assets)
    if orphans > 0:
        print(f"DB에 행이 없는 오브젝트: {orphans}건 (참조되지 않으므로 정상)")

    if missing:
        print(f"\n✗ 원본은 있는데 변형이 하나라도 빠진 READY 자산 {len(missing)}건 — 불변식 위반")
        for key in missing[:10]:
            print(f"    {key}")
        if len(missing) > 10:
            print(f"    … 외 {len(missing) - 10}건")
        print("  backfill_thumbnails.py 를 돌릴 것.")
    if missing_originals:
        print(f"\n원본도 없어 변형을 만들 수 없는 READY 자산 {len(missing_originals)}건:")
        for key in missing_originals:
            print(f"    {key}")
    if missing:
        return 1
    if missing_originals:
        print("\n✓ 원본이 있는 자산은 불변식 충족 — 남은 것은 원본 없음뿐(exit 2)")
        return 2

    print("\n✓ 불변식 충족 — 변형이 빠진 READY 자산 0건")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="버킷의 변형(썸네일·표시용) 상태를 감사한다(읽기 전용).")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="자산별 용량·치수를 출력한다(치수 확인을 위해 오브젝트를 내려받는다)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
