"""장면컷(aspectRatio == "3:4") PNG 를 정확한 3:4 로 중앙 크롭한다 — seed-migration-goal-prompt.md SM-17.

채팅 화면의 상황컷 웰은 `aspect-3/4`(정확히 0.750) + `object-contain` 이다
(`apps/web/src/entities/chat-room/ui/MessageBubble.tsx:105,111,171,177`). 집 PC 의 `3:4`
버킷은 실제로 **896×1152 = 0.7778** 을 반환해서 `object-contain` 이 위아래 약 11px 빈 띠
(레터박스)를 남긴다 — 현행 시드(768×1024, 정확히 0.75)에는 없던 회귀다.
896 → **864**(좌우 16px씩)로 줄이면 864/1152 = **정확히 0.750** 이 된다.

    cd apps/api && uv run --env-file .env python scripts/crop_scene_images.py --dry-run
    cd apps/api && uv run --env-file .env python scripts/crop_scene_images.py

`generate_seed_images.py` 실행 뒤, `seed_dev.py`/`upload_seed_images.py` 전에 돈다 —
`_thumb.webp`·블러본은 크롭된 원본에서 파생되므로 순서가 고정된다.

대상은 `image_prompts.json` 에서 `aspectRatio == "3:4"` 인 slug 뿐이다(현재 장면컷 4건).
스토리(2:3)·캐릭터(1:1)는 `object-cover` 라 CSS 가 비율 차이를 흡수하므로 건드리지 않는다.

이미 정확히 3:4 인 파일은 건너뛴다(재실행 안전 — SM-14 재시도 루프와 섞인다). 로컬에 PNG 가
없는 slug 는 조용히 넘기지 않고 목록으로 보고한다(`upload_seed_images.py` 의 침묵 스킵이
이 저장소의 알려진 함정이다).
"""

import argparse
import sys

from PIL import Image

from generate_seed_images import ImagePromptSpec, load_prompt_specs
from seed_content.loader import SeedContentError

# width:height. 폭이 넘치면 좌우를, 높이가 넘치면 위아래를 중앙 기준으로 자른다 — 현재
# 장면컷은 항상 896x1152(폭 초과)라 좌우 크롭만 실제로 쓰이지만, 규칙은 어느 쪽으로
# 어긋나든 동작하게 일반형으로 둔다.
TARGET_RATIO = (3, 4)


def crop_to_target_ratio(image: Image.Image) -> Image.Image | None:
    """중앙에서 3:4 를 만족하는 최대 영역을 자른다(리사이즈 없음). 이미 정확한 비율이면 `None`."""
    width, height = image.size
    ratio_w, ratio_h = TARGET_RATIO
    if width * ratio_h == height * ratio_w:
        return None
    if width * ratio_h > height * ratio_w:
        target_width = height * ratio_w // ratio_h
        left = (width - target_width) // 2
        return image.crop((left, 0, left + target_width, height))
    target_height = width * ratio_h // ratio_w
    top = (height - target_height) // 2
    return image.crop((0, top, width, top + target_height))


def main() -> int:
    args = _parse_args()
    try:
        specs = load_prompt_specs()
    except SeedContentError as exc:
        print(f"프롬프트 파일을 읽지 못했다 — {exc}")
        return 1

    return _crop_all(_scene_specs(specs), dry_run=args.dry_run)


def _scene_specs(specs: list[ImagePromptSpec]) -> list[ImagePromptSpec]:
    """`aspectRatio == "3:4"` 인 항목만 고른다 — 스토리(2:3)·캐릭터(1:1)는 `object-cover` 라
    CSS 가 비율 차이를 흡수하므로 대상이 아니다."""
    return [spec for spec in specs if spec.aspect_ratio == "3:4"]


def _crop_all(scene_specs: list[ImagePromptSpec], *, dry_run: bool) -> int:
    print(f"장면컷(aspectRatio == 3:4) {len(scene_specs)}건")

    missing: list[str] = []
    skipped: list[str] = []
    cropped: list[str] = []
    failed: list[str] = []

    for spec in scene_specs:
        if not spec.path.is_file():
            missing.append(spec.slug)
            continue

        try:
            with Image.open(spec.path) as image:
                image.load()
                before = image.size
                result = crop_to_target_ratio(image)
                if result is not None:
                    result.load()  # 파일 핸들이 닫힌 뒤에도 쓸 수 있게 지금 당겨온다(크롭은 lazy)
        except Exception as exc:
            print(f"  ✗ {spec.slug}: {exc!r}")
            failed.append(spec.slug)
            continue

        if result is None:
            print(f"  - {spec.slug}: 이미 {before[0]}x{before[1]}(3:4) — 건너뜀")
            skipped.append(spec.slug)
            continue

        after = result.size
        if dry_run:
            print(f"  · {spec.slug}: {before[0]}x{before[1]} → {after[0]}x{after[1]} (dry-run)")
            continue

        try:
            result.save(spec.path, format="PNG")
        except Exception as exc:
            print(f"  ✗ {spec.slug}: {exc!r}")
            failed.append(spec.slug)
            continue
        print(f"  ✓ {spec.slug}: {before[0]}x{before[1]} → {after[0]}x{after[1]}")
        cropped.append(spec.slug)

    if missing:
        print(f"\n파일 없음 {len(missing)}건 — 건너뜀: {', '.join(missing)}")

    if dry_run:
        print("\n(--dry-run: 파일 안 씀)")
        return 1 if failed else 0

    if failed:
        print(f"\n실패 {len(failed)}건: {', '.join(failed)}")
        return 1
    print(f"\n완료 — 크롭 {len(cropped)}건, 이미 3:4 라 건너뜀 {len(skipped)}건")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="장면컷 PNG 를 정확한 3:4 로 중앙 크롭한다.")
    parser.add_argument(
        "--dry-run", action="store_true", help="파일을 쓰지 않고 무엇을 어떻게 자를지만 출력한다"
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
