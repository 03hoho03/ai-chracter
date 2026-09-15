"""`scripts/crop_scene_images.py` 의 크롭·멱등·대상 선별 — seed-migration-goal-prompt.md SM-17."""

from pathlib import Path

import pytest
from PIL import Image

import crop_scene_images
import generate_seed_images
from api.images.models import AspectRatio
from generate_seed_images import ImagePromptSpec


def _make_spec(slug: str, aspect_ratio: AspectRatio = "3:4") -> ImagePromptSpec:
    return ImagePromptSpec(
        slug=slug, prompt="p", model="v1", aspect_ratio=aspect_ratio, style=generate_seed_images.DEFAULT_STYLE
    )


def _save(path: Path, width: int, height: int) -> None:
    """좌우를 다른 색으로 칠해 중앙 크롭이 실제로 가운데를 잘랐는지(좌우 띠가 사라졌는지) 확인한다."""
    image = Image.new("RGB", (width, height), (0, 0, 0))
    for x in range(width):
        image.putpixel((x, 0), (255, 0, 0) if x < width // 2 else (0, 0, 255))
    image.save(path)


def test_crops_896x1152_to_864x1152_around_the_center(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """896x1152 장면컷은 좌우 16px씩 잘려 864x1152 가 돼야 채팅 웰(aspect-3/4)에 레터박스가 안 생긴다."""
    monkeypatch.setattr(generate_seed_images, "IMAGES_DIR", tmp_path)
    spec = _make_spec("romance-3rdloop-dj-scene1")
    _save(spec.path, 896, 1152)

    exit_code = crop_scene_images._crop_all([spec], dry_run=False)

    assert exit_code == 0
    with Image.open(spec.path) as result:
        assert result.size == (864, 1152)
        left_edge = result.getpixel((0, 0))
        right_edge = result.getpixel((863, 0))
    assert left_edge == (255, 0, 0)  # 원본 좌측(빨강) 색이 여전히 남아 있다
    assert right_edge == (0, 0, 255)  # 원본 우측(파랑) 색이 여전히 남아 있다 — 중앙만 잘렸다는 뜻


def test_rerunning_an_already_3_4_file_does_not_change_its_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """멱등 — SM-14 재시도 루프와 섞이므로 이미 3:4 인 파일을 재실행해도 안전해야 한다."""
    monkeypatch.setattr(generate_seed_images, "IMAGES_DIR", tmp_path)
    spec = _make_spec("romance-3rdloop-dj-scene1")
    _save(spec.path, 864, 1152)
    before_bytes = spec.path.read_bytes()

    exit_code = crop_scene_images._crop_all([spec], dry_run=False)

    assert exit_code == 0
    assert spec.path.read_bytes() == before_bytes


def test_only_aspect_ratio_3_4_specs_get_cropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스토리(2:3)·캐릭터(1:1)는 `object-cover` 가 비율을 흡수하므로 대상에서 빠져야 한다."""
    monkeypatch.setattr(generate_seed_images, "IMAGES_DIR", tmp_path)
    scene = _make_spec("romance-3rdloop-dj-scene1", "3:4")
    story = _make_spec("romance-3rdloop", "2:3")
    character = _make_spec("mia", "1:1")
    _save(scene.path, 896, 1152)
    _save(story.path, 800, 1200)
    _save(character.path, 900, 900)
    story_bytes = story.path.read_bytes()
    character_bytes = character.path.read_bytes()

    selected = crop_scene_images._scene_specs([story, scene, character])
    exit_code = crop_scene_images._crop_all(selected, dry_run=False)

    assert exit_code == 0
    with Image.open(scene.path) as image:
        assert image.size == (864, 1152)  # 유일한 3:4 대상 — 크롭됨
    assert story.path.read_bytes() == story_bytes  # 2:3 — 손대지 않음
    assert character.path.read_bytes() == character_bytes  # 1:1 — 손대지 않음
