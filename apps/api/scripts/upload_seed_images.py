"""생성된 시드 이미지를 현재 env 가 가리키는 오브젝트 스토리지에 올린다 (DB 는 안 건드린다).

    # 로컬 moto
    cd apps/api && uv run --env-file .env python scripts/upload_seed_images.py --dry-run
    cd apps/api && uv run --env-file .env python scripts/upload_seed_images.py

    # 프로덕션 R2 (Cloud Run env 를 그대로 주입, 시크릿을 디스크에 안 남긴다)
    cd apps/api && env S3_ENDPOINT_URL=… S3_BUCKET_NAME=… AWS_ACCESS_KEY_ID=… \
        AWS_SECRET_ACCESS_KEY=… AWS_REGION=auto uv run python scripts/upload_seed_images.py

`seed_dev.py` 도 같은 바이트를 올리지만 그건 DB 업서트가 본체다. 이미 시딩된 환경(프로덕션)
에서 바뀌는 건 "그 키가 가리키는 바이트"뿐이라 — `Asset.id` 도 storage key 도 slug 파생
고정값이라 두 스토리지에서 같다 — 이미지만 갈아끼우는 이 스크립트로 충분하다.

**로컬에 PNG 가 없는 slug 는 건너뛴다.** 시드가 쓰는 목업 폴백을 스토리지에 올리면 이미 올라간
진짜 아트를 목업으로 덮어쓰게 된다 — 그건 이 스크립트가 절대 하면 안 되는 일이다.
"""

import argparse
import sys
from dataclasses import dataclass

from api.assets.image_processing import (
    THUMBNAIL_CONTENT_TYPE,
    generate_blurred_image,
    generate_thumbnail,
)
from api.core.config import settings
from api.core.s3 import build_object_key, build_thumbnail_key, upload_object
from api.db.models.media import AssetKind
from seed_content.images import CONTENT_TYPE, IMAGES_DIR, asset_storage_key, situational_image_slug
from seed_content.ids import MIA_THUMBNAIL_ASSET_ID
from seed_content.loader import load_characters, load_stories

# 미아(샘플 캐릭터)의 썸네일만 slug 파생이 아니라 리터럴 자산 id 를 쓴다 — 이유는 ids.py 참고.
MIA_SLUG = "mia"
MIA_KEY = build_object_key("thumbnail", MIA_THUMBNAIL_ASSET_ID, CONTENT_TYPE)


@dataclass(frozen=True)
class Upload:
    slug: str
    key: str
    body: bytes
    content_type: str = CONTENT_TYPE


def collect_uploads() -> tuple[list[Upload], list[str]]:
    """(올릴 것, 로컬 PNG 가 없어 건너뛴 slug). 시드가 자산을 만드는 규칙을 그대로 따라간다."""
    uploads: list[Upload] = []
    missing: list[str] = []

    def add(slug: str, key: str, *, blurred: bool = False) -> None:
        path = IMAGES_DIR / f"{slug}.png"
        if not path.is_file():
            missing.append(slug)
            return
        body = path.read_bytes()
        if blurred:
            body = generate_blurred_image(body)
        uploads.append(Upload(slug, key, body))
        # READY 자산에는 항상 `_thumb.webp`가 있다는 불변식(US-004~) — 원본을 갈아끼우면
        # 썸네일도 같은 바이트에서 다시 만들어 함께 올린다.
        uploads.append(
            Upload(slug, build_thumbnail_key(key), generate_thumbnail(body), THUMBNAIL_CONTENT_TYPE)
        )

    for story in load_stories():
        add(story.slug, asset_storage_key(story.slug, AssetKind.THUMBNAIL))

    for character in load_characters():
        add(character.slug, asset_storage_key(character.slug, AssetKind.THUMBNAIL))
        # 상황별 이미지는 원본과 블러본 두 자산을 쓰고, 블러본은 원본에서 그때그때 만든다
        # (seed_content.upsert._ensure_situational_assets 와 같은 규칙).
        for order in range(len(character.payload.situational_images)):
            scene_slug = situational_image_slug(character.slug, order)
            add(scene_slug, asset_storage_key(scene_slug, AssetKind.ORIGINAL))
            add(scene_slug, asset_storage_key(scene_slug, AssetKind.BLURRED), blurred=True)

    add(MIA_SLUG, MIA_KEY)
    return uploads, sorted(set(missing))


def main() -> int:
    args = _parse_args()
    uploads, missing = collect_uploads()

    target = settings.s3_endpoint_url or "AWS S3 (기본 엔드포인트)"
    print(f"대상: {target} / 버킷 {settings.s3_bucket_name}")
    if missing:
        print(f"  - 로컬 PNG 없음 {len(missing)}건 — 건너뜀: {', '.join(missing)}")
    if not uploads:
        print("올릴 이미지가 없다 — scripts/generate_seed_images.py 로 먼저 생성할 것")
        return 1

    if args.dry_run:
        for upload in uploads:
            print(f"  · {upload.slug} → {upload.key} ({len(upload.body):,} bytes)")
        print(f"\n{len(uploads)}건 (API 호출 없음)")
        return 0

    failed: list[str] = []
    for upload in uploads:
        try:
            upload_object(upload.key, upload.body, upload.content_type)
        except Exception as exc:  # noqa: BLE001 - 한 건의 실패로 나머지를 멈추지 않는다
            print(f"  ✗ {upload.slug}: {exc!r}")
            failed.append(upload.slug)
            continue
        print(f"  ✓ {upload.slug} → {upload.key} ({len(upload.body):,} bytes)")

    if failed:
        print(f"\n실패 {len(failed)}건: {', '.join(failed)}")
        return 1
    print(f"\n완료 — {len(uploads)}건 업로드")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="시드 이미지를 현재 env 의 스토리지에 올린다.")
    parser.add_argument(
        "--dry-run", action="store_true", help="업로드 없이 대상 키 목록만 출력한다"
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
