"""`scripts/generate_seed_images.py` 의 프롬프트 파일 파싱과 실패 처리 (US-006).

Cloudflare 호출 자체는 테스트하지 않는다 — 손으로 쓰는 `image_prompts.json`(US-007)이 조용히
어긋나지 않도록 기본값·검증 실패 경로를, 그리고 한 장이 실패해도 배치가 이어지는지를 고정한다.
"""

import io
import json
from pathlib import Path

import pytest
from PIL import Image

import generate_seed_images
from api.llm.client import LLMClientError
from api.llm.image import ImageClient, ImageStylePreset
from generate_seed_images import ImagePromptSpec, load_prompt_specs
from seed_content.images import situational_image_slug
from seed_content.loader import SeedContentError, load_characters, load_stories


def _write(tmp_path: Path, items: object) -> Path:
    path = tmp_path / "image_prompts.json"
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return path


def test_applies_defaults(tmp_path: Path) -> None:
    specs = load_prompt_specs(_write(tmp_path, [{"slug": "a", "prompt": "a booth at night"}]))

    assert specs == [
        ImagePromptSpec(
            slug="a",
            prompt="a booth at night",
            model="sdxl",
            aspect_ratio="3:4",
            style=ImageStylePreset.ANIME,
        )
    ]


def test_full_prompt_appends_style_suffix(tmp_path: Path) -> None:
    specs = load_prompt_specs(_write(tmp_path, [{"slug": "a", "prompt": "a booth at night"}]))

    assert specs[0].full_prompt == "a booth at night, anime style, cel shading, clean lineart"


def test_explicit_values_win(tmp_path: Path) -> None:
    specs = load_prompt_specs(
        _write(
            tmp_path,
            [{"slug": "a", "prompt": "p", "model": "flux-schnell", "aspectRatio": "1:1", "style": "illustration"}],
        )
    )

    assert (specs[0].model, specs[0].aspect_ratio, specs[0].style.value) == (
        "flux-schnell",
        "1:1",
        "illustration",
    )


def test_rejects_aspect_ratio_the_model_does_not_support(tmp_path: Path) -> None:
    path = _write(tmp_path, [{"slug": "a", "prompt": "p", "model": "flux-schnell", "aspectRatio": "3:4"}])

    with pytest.raises(SeedContentError, match=r"image_prompts.json\[0\].*3:4"):
        load_prompt_specs(path)


def test_rejects_unknown_model_and_empty_slug(tmp_path: Path) -> None:
    with pytest.raises(SeedContentError, match="model"):
        load_prompt_specs(_write(tmp_path, [{"slug": "a", "prompt": "p", "model": "dall-e"}]))
    with pytest.raises(SeedContentError, match="slug"):
        load_prompt_specs(_write(tmp_path, [{"slug": "  ", "prompt": "p"}]))


def test_rejects_duplicate_slugs(tmp_path: Path) -> None:
    path = _write(tmp_path, [{"slug": "a", "prompt": "p"}, {"slug": "a", "prompt": "q"}])

    with pytest.raises(SeedContentError, match="중복"):
        load_prompt_specs(path)


def test_missing_file_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(SeedContentError, match="image_prompts.json"):
        load_prompt_specs(tmp_path / "image_prompts.json")


def test_committed_prompt_file_parses() -> None:
    """리포에 커밋된 실제 파일 — US-007 이 채운 뒤에도 이 테스트가 스키마를 지킨다."""
    load_prompt_specs()


def test_every_seed_content_slug_has_a_prompt() -> None:
    """프롬프트를 빠뜨린 콘텐츠는 조용히 목업 썸네일로 폴백한다 — 실패가 눈에 안 띄어서 고정한다."""
    characters = load_characters()
    expected = {story.slug for story in load_stories()}
    expected |= {character.slug for character in characters}
    expected |= {
        situational_image_slug(character.slug, order)
        for character in characters
        for order in range(len(character.payload.situational_images))
    }

    missing = expected - {spec.slug for spec in load_prompt_specs()}

    assert not missing, f"image_prompts.json 에 없는 slug: {sorted(missing)}"


class _FakeImageClient(ImageClient):
    """`fail` slug 만 세이프티 필터처럼 실패시키는 클라이언트."""

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    async def generate_image(
        self, prompt: str, style: ImageStylePreset, aspect_ratio: str
    ) -> tuple[bytes, str]:
        if "fail" in prompt:
            raise LLMClientError("blank single-color image")
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"


async def test_one_failure_does_not_stop_the_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generate_seed_images, "IMAGES_DIR", tmp_path)
    monkeypatch.setattr(generate_seed_images, "build_image_client", _FakeImageClient)
    specs = load_prompt_specs(
        _write(tmp_path, [{"slug": "bad", "prompt": "fail"}, {"slug": "good", "prompt": "ok"}])
    )

    exit_code = await generate_seed_images._generate_all(
        specs, force=False, sleep_seconds=0.0, retry_delays=()
    )

    assert exit_code == 1  # 실패가 있었음을 종료코드로 알린다
    assert not (tmp_path / "bad.png").exists()
    assert (tmp_path / "good.png").exists()  # 실패 다음 항목도 계속 생성된다


class _FlakyImageClient(ImageClient):
    """처음 한 번만 실패하는 클라이언트 — Cloudflare 의 일시적 blip 재현."""

    calls = 0

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    async def generate_image(
        self, prompt: str, style: ImageStylePreset, aspect_ratio: str
    ) -> tuple[bytes, str]:
        _FlakyImageClient.calls += 1
        if _FlakyImageClient.calls == 1:
            raise LLMClientError("429 rate limited")
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"


async def test_transient_failure_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FlakyImageClient.calls = 0
    monkeypatch.setattr(generate_seed_images, "IMAGES_DIR", tmp_path)
    monkeypatch.setattr(generate_seed_images, "build_image_client", _FlakyImageClient)
    specs = load_prompt_specs(_write(tmp_path, [{"slug": "flaky", "prompt": "ok"}]))

    exit_code = await generate_seed_images._generate_all(
        specs, force=False, sleep_seconds=0.0, retry_delays=(0.0,)
    )

    assert exit_code == 0
    assert _FlakyImageClient.calls == 2  # 첫 실패 뒤 한 번 더 시도해서 살아났다
    assert (tmp_path / "flaky.png").exists()
