"""`scripts/seed_content` 의 결정적 UUID 헬퍼와 데이터 파일 로더 (US-002)."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from seed_content.ids import SEED_NAMESPACE, seed_uuid
from seed_content.loader import (
    SeedContentError,
    load_character,
    load_characters,
    load_stories,
    load_story,
)


def _story_payload() -> dict[str, Any]:
    """검증을 통과하는 최소 스토리 — id 는 일부러 하나도 적지 않는다."""
    return {
        "name": "테스트 스토리",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "promptTemplate": "basic",
        "settingText": "세계관",
        "developmentExample": None,
        "customPrompt": None,
        "startingSetups": [
            {
                "name": "첫날",
                "prologue": "프롤로그",
                "openingMessage": None,
                "playguide": None,
                "suggestedReplies": ["안녕"],
                "statDefs": [
                    {
                        "name": "신뢰",
                        "icon": "heart",
                        "color": "#888888",
                        "minValue": 0,
                        "maxValue": 100,
                        "initialValue": 50,
                        "unit": None,
                        "description": "신뢰도",
                    }
                ],
                "endings": [
                    {
                        "name": "해피엔딩",
                        "turnCountGate": 10,
                        "judgmentPrompt": "신뢰가 높은 상태로 끝났는가",
                        "epilogue": None,
                        "hint": None,
                        "statRules": [
                            {
                                "kind": "group",
                                "rules": [
                                    {
                                        "kind": "rule",
                                        "statId": "00000000-0000-4000-8000-000000000001",
                                        "operator": "gte",
                                        "threshold": 80,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "keywordNotes": [
            {
                "infoText": "설정 메모",
                "triggerKeywords": ["라디오", "부스"],
                "startingSetupId": None,
            }
        ],
        "shortcuts": [{"name": "단축어", "description": "설명", "prompt": "프롬프트"}],
        "description": "상세 설명",
        "genreId": "b8a1e6b0-1c1a-4b8a-9b0a-000000000001",
        "target": "female",
        "hashtags": ["라디오"],
        "visibility": "public",
    }


def _character_payload() -> dict[str, Any]:
    return {
        "name": "테스트 캐릭터",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "intro": "인트로",
        "exampleDialogues": [{"userLine": "안녕", "characterLine": "응, 안녕"}],
        "characterPrompt": "너는 테스트 캐릭터다.",
        "playguide": None,
        "situationalImages": [{"triggerCondition": "처음 웃는 순간"}],
        "description": "상세 설명",
        "genreId": "b8a1e6b0-1c1a-4b8a-9b0a-000000000001",
        "target": "female",
        "hashtags": [],
        "visibility": "public",
    }


def _write(directory: Path, slug: str, payload: Any) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slug}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_seed_uuid_is_deterministic() -> None:
    assert seed_uuid("story", "romance-3rdloop") == seed_uuid("story", "romance-3rdloop")
    # 파트는 ":" 로 이어 붙인다 — 나눠 넘기든 붙여 넘기든 같은 값이어야 한다.
    assert seed_uuid("story", "romance-3rdloop") == seed_uuid("story:romance-3rdloop")
    assert seed_uuid("story", "romance-3rdloop") == uuid.uuid5(
        SEED_NAMESPACE, "story:romance-3rdloop"
    )
    assert seed_uuid("story", "romance-3rdloop").version == 5


def test_seed_uuid_differs_per_path() -> None:
    assert seed_uuid("story", "a") != seed_uuid("story", "b")
    assert seed_uuid("story", "a") != seed_uuid("character", "a")
    assert seed_uuid("story", "a", "setup") != seed_uuid("story", "a")


def test_load_story_derives_entity_ids_from_position(tmp_path: Path) -> None:
    path = _write(tmp_path, "romance-3rdloop", _story_payload())

    payload = load_story(path)

    setup = payload.starting_setups[0]
    setup_path = "story:romance-3rdloop:startingSetups[0]"
    assert setup.id == seed_uuid(setup_path)
    assert setup.stat_defs[0].id == seed_uuid(f"{setup_path}:statDefs[0]")
    ending = setup.endings[0]
    ending_path = f"{setup_path}:endings[0]"
    assert ending.id == seed_uuid(ending_path)
    # 그룹과 그 안의 규칙까지 재귀적으로 채워진다.
    group = ending.stat_rules[0]
    assert group.kind == "group"
    assert group.id == seed_uuid(f"{ending_path}:statRules[0]")
    assert group.rules[0].id == seed_uuid(f"{ending_path}:statRules[0]:rules[0]")
    assert payload.keyword_notes[0].id == seed_uuid("story:romance-3rdloop:keywordNotes[0]")
    assert payload.shortcuts[0].id == seed_uuid("story:romance-3rdloop:shortcuts[0]")


def test_load_story_is_stable_across_reloads(tmp_path: Path) -> None:
    path = _write(tmp_path, "romance-3rdloop", _story_payload())

    first = load_story(path)
    second = load_story(path)

    assert first == second


def test_load_story_keeps_explicit_id(tmp_path: Path) -> None:
    explicit = "5eed0000-0000-4000-8000-0000000000ff"
    raw = _story_payload()
    raw["shortcuts"][0]["id"] = explicit
    path = _write(tmp_path, "romance-3rdloop", raw)

    payload = load_story(path)

    assert payload.shortcuts[0].id == uuid.UUID(explicit)


def test_load_character_derives_entity_ids(tmp_path: Path) -> None:
    path = _write(tmp_path, "romance-3rdloop-dj", _character_payload())

    payload = load_character(path)

    root = "character:romance-3rdloop-dj"
    # exampleDialogues 의 id 는 uuid 가 아니라 str 이지만 파생 방식은 같다.
    assert payload.example_dialogues[0].id == str(seed_uuid(f"{root}:exampleDialogues[0]"))
    assert payload.situational_images[0].id == seed_uuid(f"{root}:situationalImages[0]")


def test_load_story_reports_file_name_on_schema_mismatch(tmp_path: Path) -> None:
    raw = _story_payload()
    del raw["oneLiner"]
    path = _write(tmp_path, "broken-story", raw)

    with pytest.raises(SeedContentError, match="broken-story.json"):
        load_story(path)


def test_load_story_reports_file_name_on_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "not-json.json"
    path.write_text("{ nope", encoding="utf-8")

    with pytest.raises(SeedContentError, match="not-json.json"):
        load_story(path)


def test_load_story_reports_file_name_when_top_level_is_not_object(tmp_path: Path) -> None:
    path = _write(tmp_path, "list-story", [_story_payload()])

    with pytest.raises(SeedContentError, match="list-story.json"):
        load_story(path)


def test_load_stories_returns_empty_list_without_data_files(tmp_path: Path) -> None:
    assert load_stories(tmp_path / "missing") == []
    assert load_characters(tmp_path / "missing") == []


def test_load_stories_reads_every_file_sorted_by_slug(tmp_path: Path) -> None:
    _write(tmp_path, "b-story", _story_payload())
    _write(tmp_path, "a-story", _story_payload())

    stories = load_stories(tmp_path)

    assert [story.slug for story in stories] == ["a-story", "b-story"]
    # slug 가 다르면 같은 내용이어도 다른 콘텐츠다.
    assert stories[0].payload.starting_setups[0].id != stories[1].payload.starting_setups[0].id
