"""status=READY 인 기존 자산 전량에 썸네일(`{원본키}_thumb.webp`)을 백필한다.

US-004~006 이후 새로 READY 가 되는 자산은 생성 경로가 썸네일을 함께 만들지만, 그 전에
올라간 자산에는 없다 — 응답을 썸네일 키로 전환(US-008~009)하기 전에 반드시 이 스크립트를
돌려 "READY 자산에는 항상 `_thumb.webp`가 있다"는 불변식을 소급 성립시킨다.

    # 로컬 (docker dev 스택의 postgres/moto)
    cd apps/api && uv run --env-file .env python scripts/backfill_thumbnails.py --dry-run
    cd apps/api && uv run --env-file .env python scripts/backfill_thumbnails.py

    # 프로덕션 (Neon + R2, 시크릿을 디스크에 안 남긴다)
    cd apps/api && env DATABASE_URL=… S3_ENDPOINT_URL=… S3_BUCKET_NAME=… \
        AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… AWS_REGION=auto \
        uv run python scripts/backfill_thumbnails.py

이미 `_thumb.webp`가 존재하는 자산은 건너뛴다(재실행 안전). 개별 자산 실패(원본 유실 등)는
스크립트를 멈추지 않고 수집했다가 마지막에 요약하고 exit code 1 로 알린다.
"""

import argparse
import asyncio
import os
import sys

# boto3(api.core.s3 모듈 전역 클라이언트)는 자격증명이 "존재"해야 하고 moto 엔드포인트를
# 알아야 한다. `--env-file .env` 로 실행하면 이미 채워져 있고, 아니면 여기서 기본값.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:5001")

from sqlalchemy import select  # noqa: E402

from api.assets.image_processing import THUMBNAIL_CONTENT_TYPE, generate_thumbnail  # noqa: E402
from api.core.config import settings  # noqa: E402
from api.core.s3 import (  # noqa: E402
    build_thumbnail_key,
    download_object,
    get_object_size,
    upload_object,
)
from api.db.models.media import Asset, AssetStatus  # noqa: E402
from api.db.session import async_session_factory  # noqa: E402


async def _load_ready_assets() -> list[Asset]:
    async with async_session_factory() as session:
        result = await session.scalars(
            select(Asset).where(Asset.status == AssetStatus.READY).order_by(Asset.created_at)
        )
        return list(result.all())


def main() -> int:
    args = _parse_args()
    assets = asyncio.run(_load_ready_assets())

    target = settings.s3_endpoint_url or "AWS S3 (기본 엔드포인트)"
    print(f"대상: {target} / 버킷 {settings.s3_bucket_name}")

    targets: list[Asset] = []
    skipped = 0
    for asset in assets:
        if get_object_size(build_thumbnail_key(asset.storage_key)) is not None:
            skipped += 1
        else:
            targets.append(asset)
    print(f"READY 자산 {len(assets)}건 — 생성 대상 {len(targets)}건, 이미 있음 {skipped}건")

    if args.dry_run:
        print("(--dry-run: 업로드 없음)")
        return 0

    failed: list[str] = []
    for asset in targets:
        thumbnail_key = build_thumbnail_key(asset.storage_key)
        try:
            original = download_object(asset.storage_key)
            upload_object(thumbnail_key, generate_thumbnail(original), THUMBNAIL_CONTENT_TYPE)
        except Exception as exc:  # noqa: BLE001 - 한 건의 실패로 나머지를 멈추지 않는다
            print(f"  ✗ {asset.storage_key}: {exc!r}")
            failed.append(asset.storage_key)
            continue
        print(f"  ✓ {asset.storage_key} → {thumbnail_key}")

    if failed:
        print(f"\n실패 {len(failed)}건: {', '.join(failed)}")
        return 1
    print(f"\n완료 — {len(targets)}건 생성")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="READY 자산 전량에 썸네일을 백필한다.")
    parser.add_argument(
        "--dry-run", action="store_true", help="업로드 없이 대상/스킵 개수만 출력한다"
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
