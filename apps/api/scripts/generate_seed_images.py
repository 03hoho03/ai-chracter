"""시드 이미지 생성 CLI — `seed_content/data/image_prompts.json` 의 프롬프트를 이미지 스토어에 떨군다.

    cd apps/api && uv run --env-file .env python scripts/generate_seed_images.py --dry-run
    cd apps/api && uv run --env-file .env python scripts/generate_seed_images.py
    cd apps/api && uv run --env-file .env python scripts/generate_seed_images.py --only romance-3rdloop --force

프롬프트 파일은 커밋하고 생성물(`seed_content/images/{slug}.png`)은 gitignore 다 — 다른
머신에서는 이 스크립트로 다시 뽑는다(Cloudflare 에 시드값을 못 보내므로 원본과 픽셀이
같지는 않다). 이미지가 없는 머신은 시드가 목업 썸네일로 대체하므로 이 단계는 선택이다.

Cloudflare 는 간헐적으로 실패한다(빈 메시지의 `LLMClientError` = 일시적 blip). 한 장이
실패해도 나머지는 계속 생성하고, 끝에 실패 목록을 찍는다 — `--only <slug>` 로 재시도할 것.

무료 티어는 하루 10,000 뉴런을 계정 전체가 나눠 쓰므로 30장짜리 배치는 한 번에 몰아치지
않는다: 장과 장 사이에 `--sleep` 만큼 쉬고, 실패한 장은 `RETRY_DELAYS` 간격으로 두 번 더
되짚는다(429 든 일시적 blip 이든 같은 취급 — 응답이 둘을 구분해주지 않는다).
"""

import argparse
import asyncio
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from api.core.config import settings
from api.images.models import IMAGE_MODELS_BY_ID, AspectRatio, ImageModelId
from api.llm.client import LLMClientError
from api.llm.dependencies import build_image_client
from api.llm.image import ImageStylePreset, apply_style_preset
from seed_content.images import IMAGES_DIR
from seed_content.loader import DATA_DIR, SeedContentError

PROMPTS_PATH = DATA_DIR / "image_prompts.json"

# 인물 컷이 기본이라 세로 3:4 다. flux-schnell 은 1:1 전용이라 인물에 쓰지 않는다.
DEFAULT_MODEL: ImageModelId = "sdxl"
DEFAULT_ASPECT_RATIO: AspectRatio = "3:4"
DEFAULT_STYLE = ImageStylePreset.ANIME

# 장과 장 사이의 기본 간격(초)과, 실패한 장을 되짚는 간격. 뒤로 갈수록 벌려 쿼터가 실제로
# 마른 경우에도 무의미한 연타가 되지 않게 한다.
DEFAULT_SLEEP_SECONDS = 2.0
RETRY_DELAYS: tuple[float, ...] = (5.0, 20.0)

# JSON 의 문자열을 Literal 타입으로 좁히는 통로 (캐스트 없이).
_MODEL_IDS: dict[str, ImageModelId] = {model_id: model_id for model_id in IMAGE_MODELS_BY_ID}
_STYLE_NAMES = sorted(style.value for style in ImageStylePreset)


@dataclass(frozen=True)
class ImagePromptSpec:
    slug: str
    prompt: str
    model: ImageModelId
    aspect_ratio: AspectRatio
    style: ImageStylePreset

    @property
    def path(self) -> Path:
        """생성물 경로. 시드는 이 파일명(`{slug}.png`)으로만 이미지를 찾는다."""
        return IMAGES_DIR / f"{self.slug}.png"

    @property
    def full_prompt(self) -> str:
        """실제로 모델에 나가는 문자열 — 스타일 프리셋 접미까지 붙은 형태."""
        return apply_style_preset(self.prompt, self.style)


def load_prompt_specs(path: Path = PROMPTS_PATH) -> list[ImagePromptSpec]:
    """프롬프트 배열을 읽어 검증한다. 어긋난 항목은 위치를 담은 `SeedContentError` 로 죽는다."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeedContentError(f"{path.name}: JSON 을 읽지 못했다 — {exc}") from exc
    if not isinstance(raw, list):
        raise SeedContentError(f"{path.name}: 최상위가 JSON 배열이 아니다")

    specs = [_parse_spec(path.name, index, item) for index, item in enumerate(raw)]
    seen: set[str] = set()
    for spec in specs:
        if spec.slug in seen:
            raise SeedContentError(f"{path.name}: slug 가 중복이다 — {spec.slug}")
        seen.add(spec.slug)
    return specs


def main() -> int:
    args = _parse_args()
    try:
        specs = load_prompt_specs()
    except SeedContentError as exc:
        print(f"프롬프트 파일을 읽지 못했다 — {exc}")
        return 1

    if args.only is not None:
        specs = [spec for spec in specs if spec.slug == args.only]
        if not specs:
            print(f"--only {args.only} 에 해당하는 항목이 {PROMPTS_PATH.name} 에 없다")
            return 1

    if args.dry_run:
        _print_dry_run(specs)
        return 0

    if not settings.cloudflare_account_id or not settings.cloudflare_api_token:
        print(
            "CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN 이 비어 있어 이미지를 생성할 수 없다.\n"
            "  apps/api/.env 에 두 값을 넣고 `uv run --env-file .env python "
            "scripts/generate_seed_images.py` 로 실행할 것.\n"
            "  (--dry-run 은 키 없이도 조립된 프롬프트를 보여준다)"
        )
        return 1

    return asyncio.run(
        _generate_all(
            specs,
            force=bool(args.force),
            sleep_seconds=float(args.sleep),
            retry_delays=RETRY_DELAYS,
        )
    )


async def _generate_all(
    specs: list[ImagePromptSpec],
    *,
    force: bool,
    sleep_seconds: float,
    retry_delays: tuple[float, ...],
) -> int:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    called = False
    for spec in specs:
        if spec.path.exists() and not force:
            print(f"  - {spec.slug}: 이미 있음 — 건너뜀 (--force 로 재생성)")
            continue
        if called and sleep_seconds > 0:
            await asyncio.sleep(sleep_seconds)
        print(f"  · {spec.slug}: {spec.model} / {spec.aspect_ratio} / {spec.style.value} 생성 중…")
        called = True
        try:
            data, mime_type = await _generate_with_retry(spec, retry_delays)
        except LLMClientError as exc:
            # 세이프티 필터(단색 이미지)든 일시적 blip 이든 한 장의 실패로 배치를 멈추지 않는다.
            print(f"  ✗ {spec.slug}: {exc}")
            failed.append(spec.slug)
            continue
        spec.path.write_bytes(_as_png(data, mime_type))
        print(f"  ✓ {spec.slug} → {spec.path} ({spec.path.stat().st_size:,} bytes)")

    if failed:
        print(f"\n실패 {len(failed)}건: {', '.join(failed)} — `--only <slug>` 로 재시도할 것")
        return 1
    print(f"\n완료 — {IMAGES_DIR}")
    return 0


async def _generate_with_retry(
    spec: ImagePromptSpec, retry_delays: tuple[float, ...]
) -> tuple[bytes, str]:
    """마지막 시도의 실패는 그대로 올린다 — 배치 전체를 멈출지는 호출부가 정한다."""
    client = build_image_client(spec.model)
    for delay in retry_delays:
        try:
            return await client.generate_image(spec.prompt, spec.style, spec.aspect_ratio)
        except LLMClientError as exc:
            print(f"    ↻ {spec.slug}: {exc} — {delay:.0f}s 뒤 재시도")
            await asyncio.sleep(delay)
    return await client.generate_image(spec.prompt, spec.style, spec.aspect_ratio)


def _print_dry_run(specs: list[ImagePromptSpec]) -> None:
    print(f"{PROMPTS_PATH} — {len(specs)}개 항목 (API 호출 없음)\n")
    for spec in specs:
        exists = " [이미 있음]" if spec.path.exists() else ""
        print(f"- {spec.slug}{exists}")
        print(f"    model={spec.model} aspectRatio={spec.aspect_ratio} style={spec.style.value}")
        print(f"    prompt: {spec.full_prompt}")


def _parse_spec(filename: str, index: int, item: object) -> ImagePromptSpec:
    where = f"{filename}[{index}]"
    if not isinstance(item, dict):
        raise SeedContentError(f"{where}: 항목이 JSON 객체가 아니다")

    model_raw = item.get("model", DEFAULT_MODEL)
    if model_raw not in _MODEL_IDS:
        raise SeedContentError(
            f"{where}: 알 수 없는 model {model_raw!r} — {sorted(_MODEL_IDS)} 중 하나여야 한다"
        )
    model = _MODEL_IDS[model_raw]

    supported = {ratio: ratio for ratio in IMAGE_MODELS_BY_ID[model].supported_aspect_ratios}
    aspect_raw = item.get("aspectRatio", DEFAULT_ASPECT_RATIO)
    if aspect_raw not in supported:
        raise SeedContentError(
            f"{where}: {model} 이 지원하지 않는 aspectRatio {aspect_raw!r} — "
            f"{sorted(supported)} 중 하나여야 한다"
        )

    style_raw = item.get("style", DEFAULT_STYLE.value)
    try:
        style = ImageStylePreset(style_raw)
    except ValueError as exc:
        raise SeedContentError(
            f"{where}: 알 수 없는 style {style_raw!r} — {_STYLE_NAMES} 중 하나여야 한다"
        ) from exc

    return ImagePromptSpec(
        slug=_require_text(where, item, "slug"),
        prompt=_require_text(where, item, "prompt"),
        model=model,
        aspect_ratio=supported[aspect_raw],
        style=style,
    )


def _require_text(where: str, item: dict[Any, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SeedContentError(f"{where}: {key} 가 비어 있다")
    return value


def _as_png(data: bytes, mime_type: str) -> bytes:
    """시드 스토어는 `{slug}.png` 를 image/png 로 올린다 — JPEG 를 주는 모델(FLUX)이면 변환."""
    if mime_type.startswith("image/png"):
        return data
    buffer = io.BytesIO()
    with Image.open(io.BytesIO(data)) as image:
        image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="시드 이미지를 image_prompts.json 대로 생성한다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--only", metavar="SLUG", help="이 slug 하나만 생성한다")
    parser.add_argument("--force", action="store_true", help="이미 있는 PNG 도 다시 생성한다")
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        metavar="SECONDS",
        help=f"장과 장 사이 대기 시간 (기본 {DEFAULT_SLEEP_SECONDS}초)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="API 호출 없이 조립된 프롬프트 목록만 출력한다"
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
