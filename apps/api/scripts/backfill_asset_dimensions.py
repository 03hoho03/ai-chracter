"""status=READY 인 기존 자산에 픽셀 너비·높이(`assets.width`·`height`)를 채운다.

크기 컬럼이 생긴 뒤로 새로 READY 가 되는 자산은 생성 경로가 크기를 함께 적지만, 그 전에 READY 가 된
자산은 비어 있다. 비어 있는 자산은 화면이 고정 비율 칸으로 그리므로 동작은 하지만, 원본 비율로
그리려면 이 스크립트로 소급해 채운다. 원본 키를 내려받아 Pillow 로 크기를 읽는다(썸네일이 아니라 원본).

    # 로컬 (docker 스택의 postgres/moto — `.env` 가 가리키는 곳)
    cd apps/api && uv run --env-file .env python scripts/backfill_asset_dimensions.py --dry-run
    cd apps/api && uv run --env-file .env python scripts/backfill_asset_dimensions.py

운영에서 돌리는 방식(배포 이미지로 `docker run … python scripts/…`)은 `DEPLOY.md` 를 따른다.

기본은 크기가 비어 있는 READY 자산만 다룬다(재실행 안전 — 채운 행은 다음 실행에서 대상이 아니다).
`--force` 는 이미 크기가 있는 자산도 다시 잰다 — `scripts/upload_seed_images.py` 처럼 DB 는 그대로 두고
같은 키의 바이트만 갈아 끼운 뒤에는 저장된 크기가 낡기 때문이다. 행마다 커밋하므로 중간에 멈춰도 채운
행은 남는다. 개별 자산 실패(원본 유실 등)는 그 행을 비운 채 두고 수집했다가 마지막에 요약하고
exit code 1 로 알린다.
"""

import argparse
import asyncio
import os
import sys
from collections import Counter

# boto3(api.core.s3 모듈 전역 클라이언트)는 자격증명이 "존재"해야 하고 moto 엔드포인트를
# 알아야 한다. `--env-file .env` 로 실행하면 이미 채워져 있고, 아니면 여기서 기본값.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:5001")

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.assets.image_processing import read_image_size
from api.core.config import settings
from api.core.s3 import download_object
from api.db.models.media import Asset, AssetStatus


async def run(session: AsyncSession, *, dry_run: bool, force: bool) -> int:
    statement = select(Asset).where(Asset.status == AssetStatus.READY).order_by(Asset.created_at)
    if not force:
        statement = statement.where(or_(Asset.width.is_(None), Asset.height.is_(None)))
    targets = list((await session.scalars(statement)).all())

    target = settings.s3_endpoint_url or "AWS S3 (기본 엔드포인트)"
    print(f"대상: {target} / 버킷 {settings.s3_bucket_name}")
    counts = Counter(asset.kind.value for asset in targets)
    by_kind = ", ".join(f"{kind} {count}" for kind, count in sorted(counts.items())) or "없음"
    print(f"{'다시 잴' if force else '크기가 빈'} READY 자산 {len(targets)}건 — {by_kind}")

    if dry_run:
        print("(--dry-run: 쓰기 없음)")
        return 0

    failed: list[str] = []
    for asset in targets:
        try:
            width, height = read_image_size(download_object(asset.storage_key))
        except Exception as exc:
            print(f"  ✗ {asset.storage_key}: {exc!r}")
            failed.append(asset.storage_key)
            continue
        asset.width, asset.height = width, height
        await session.commit()
        print(f"  ✓ {asset.storage_key} → {width}×{height}")

    if failed:
        print(f"\n실패 {len(failed)}건: {', '.join(failed)}")
        return 1
    print(f"\n완료 — {len(targets)}건 기록")
    return 0


async def _main(args: argparse.Namespace) -> int:
    from api.db.session import async_session_factory

    async with async_session_factory() as session:
        return await run(session, dry_run=args.dry_run, force=args.force)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="READY 자산에 픽셀 너비·높이를 채운다.")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 kind 별 대상 수만 출력한다")
    parser.add_argument(
        "--force", action="store_true", help="이미 크기가 있는 자산도 다시 잰다(바이트만 갈아 끼운 뒤)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(_parse_args())))
