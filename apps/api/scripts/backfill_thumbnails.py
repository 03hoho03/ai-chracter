"""status=READY 인 기존 자산 전량에 빠진 변형(`{원본키}_thumb.webp`·`{원본키}_display.webp`)을 백필한다.

변형 생성이 들어간 뒤로 새로 READY 가 되는 자산은 생성 경로가 변형을 함께 만들지만, 그 전에
올라간 자산에는 없다 — 응답을 변형 키로 전환하기 전에 반드시 이 스크립트를
돌려 "READY 자산에는 항상 변형 전부가 있다"는 불변식을 소급 성립시킨다.

    # 로컬 (docker dev 스택의 postgres/moto)
    cd apps/api && uv run --env-file .env python scripts/backfill_thumbnails.py --dry-run
    cd apps/api && uv run --env-file .env python scripts/backfill_thumbnails.py

    # 프로덕션 (Neon + R2, 시크릿을 디스크에 안 남긴다)
    cd apps/api && env DATABASE_URL=… S3_ENDPOINT_URL=… S3_BUCKET_NAME=… \
        AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… AWS_REGION=auto \
        uv run python scripts/backfill_thumbnails.py

변형이 이미 전부 있는 자산은 원본을 내려받지 않고 건너뛰고, 일부만 있으면 빠진 것만 올린다(재실행 안전 —
있는 변형을 덮어쓰지 않는다). 개별 자산 실패는 스크립트를 멈추지 않고 수집했다가 마지막에 요약한다.

종료 코드: 0 = 전부 채움 · 1 = 다시 돌려 볼 실패가 있음 · 2 = 남은 것이 원본이 없는 자산뿐(다시 돌려도 같다).
원본 없음은 스캔에서 따로 세어 목록으로 출력한다(`--dry-run` 에서도).
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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.assets.image_processing import THUMBNAIL_CONTENT_TYPE, generate_variants
from api.core.config import settings
from api.core.s3 import (
    build_variant_keys,
    download_object,
    get_object_size,
    upload_object,
)
from api.db.models.media import Asset, AssetStatus


# 실패는 원본이 없는 자산뿐이다 — 다시 돌려도 바뀌지 않는다(처리 방법은 DEPLOY.md 의 이미지 변형 백필 절).
EXIT_ONLY_MISSING_ORIGINALS = 2


async def run(session: AsyncSession, *, dry_run: bool) -> int:
    storage_keys = list(
        await session.scalars(
            select(Asset.storage_key).where(Asset.status == AssetStatus.READY).order_by(Asset.created_at)
        )
    )
    # 목록만 읽고 트랜잭션을 바로 끝낸다. 이 뒤의 저장소 작업은 운영에서 자산 수 × R2 왕복이라 길고, 그동안
    # 트랜잭션을 열어 두면 `assets` 에 잠금이 남아 — 그사이 배포가 `assets` 를 고치는 마이그레이션을 돌리면
    # 그 마이그레이션이 이 잠금을 기다리고, 뒤따르는 모든 `assets` 조회가 그 뒤에 줄을 선다. 이후로는 DB 를 쓰지 않는다.
    await session.commit()

    target = settings.s3_endpoint_url or "AWS S3 (기본 엔드포인트)"
    print(f"대상: {target} / 버킷 {settings.s3_bucket_name}")

    # 자산마다 빠진 변형 키. 변형 이름(`_thumb.webp` 등)별로도 세어 무엇이 비었는지 보인다. 원본이 없는 자산은
    # 변형을 만들 수 없으므로 대상과 따로 센다 — 다시 돌려도 고쳐지지 않는 실패를 일시 오류와 섞지 않으려는 것이다.
    targets: list[tuple[str, set[str]]] = []
    missing_originals: list[str] = []
    missing_by_suffix: Counter[str] = Counter()
    for storage_key in storage_keys:
        missing = {key for key in build_variant_keys(storage_key) if get_object_size(key) is None}
        if not missing:
            continue
        if get_object_size(storage_key) is None:
            missing_originals.append(storage_key)
            continue
        targets.append((storage_key, missing))
        missing_by_suffix.update(key.rsplit("_", 1)[-1] for key in missing)
    print(
        f"READY 자산 {len(storage_keys)}건 — 생성 대상 {len(targets)}건, 원본 없음 {len(missing_originals)}건, "
        f"이미 있음 {len(storage_keys) - len(targets) - len(missing_originals)}건"
    )
    if missing_by_suffix:
        print("빠진 변형: " + ", ".join(f"_{suffix} {count}건" for suffix, count in sorted(missing_by_suffix.items())))
    if missing_originals:
        print(f"원본 없음(변형을 만들 수 없음) {len(missing_originals)}건:")
        for storage_key in missing_originals:
            print(f"    {storage_key}")

    if dry_run:
        print("(--dry-run: 업로드 없음)")
        return 0

    failed: list[str] = []
    for storage_key, missing in targets:
        try:
            variants = generate_variants(storage_key, download_object(storage_key))
            for variant_key, variant_bytes in variants:
                if variant_key in missing:
                    upload_object(variant_key, variant_bytes, THUMBNAIL_CONTENT_TYPE)
        except Exception as exc:
            print(f"  ✗ {storage_key}: {exc!r}")
            failed.append(storage_key)
            continue
        print(f"  ✓ {storage_key} → {', '.join(sorted(missing))}")

    if failed:
        print(f"\n실패 {len(failed)}건(다시 돌리면 남은 것만 대상): {', '.join(failed)}")
        return 1
    if missing_originals:
        print(f"\n완료 — {len(targets)}건 생성, 원본 없음 {len(missing_originals)}건은 남음(exit {EXIT_ONLY_MISSING_ORIGINALS})")
        return EXIT_ONLY_MISSING_ORIGINALS
    print(f"\n완료 — {len(targets)}건 생성")
    return 0


async def _main(args: argparse.Namespace) -> int:
    from api.db.session import async_session_factory

    async with async_session_factory() as session:
        return await run(session, dry_run=args.dry_run)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="READY 자산 전량에 빠진 변형(썸네일·표시용)을 백필한다.")
    parser.add_argument(
        "--dry-run", action="store_true", help="업로드 없이 대상/스킵 개수와 빠진 변형 수만 출력한다"
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(_parse_args())))
