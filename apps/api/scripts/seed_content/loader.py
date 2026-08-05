"""시드 콘텐츠 데이터 파일 로더.

파일 하나 = 콘텐츠 하나이고 파일명(확장자 제외)이 곧 slug 다:

    data/stories/{slug}.json      -> StoryDraftPayload
    data/characters/{slug}.json   -> CharacterDraftPayload

JSON 은 API 요청 바디와 같은 camelCase 이며 기존 draft 스키마 그대로 검증한다 — 시드
전용 스키마를 따로 두지 않는다. 그래야 빌더 API 가 받는 것과 같은 모양임이 보장되고,
스키마가 바뀌면 시드가 조용히 어긋나는 대신 파일명을 담은 에러로 죽는다.

**엔티티 id 는 JSON 에 적지 않는다.** 리스트 안의 객체마다 파일 안에서의 위치
(`story:romance-3rdloop:startingSetups[0]:endings[1]`)로 `seed_uuid` 를 파생해 채우므로
사람도 생성기도 UUID 를 쓸 필요가 없다. 대신 위치가 곧 id 라, 이미 시드된 콘텐츠의 리스트
**중간에** 항목을 끼워 넣으면 그 뒤 항목들의 id 가 전부 밀린다 — 새 항목은 뒤에 붙일 것.
JSON 이 `id` 를 직접 적어두면 그 값을 그대로 존중한다.

이 규칙 때문에 다른 항목의 id 를 참조해야 하는 필드(`keywordNotes[].startingSetupId`)는
손으로 쓸 수 없다 — 그런 키워드북은 `null`(스토리 전체 적용)로 두거나, 참조가 정말
필요해지면 그때 upsert 쪽에서 풀어야 한다.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from api.content.schemas import CharacterDraftPayload, StoryDraftPayload

from .ids import seed_uuid

DATA_DIR = Path(__file__).parent / "data"
STORIES_DIR = DATA_DIR / "stories"
CHARACTERS_DIR = DATA_DIR / "characters"

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class SeedContentError(Exception):
    """데이터 파일 하나를 읽거나 검증하는 데 실패했다 — 메시지에 항상 파일명이 들어간다."""


@dataclass(frozen=True)
class SeedStory:
    slug: str
    payload: StoryDraftPayload


@dataclass(frozen=True)
class SeedCharacter:
    slug: str
    payload: CharacterDraftPayload


def load_story(path: Path) -> StoryDraftPayload:
    return _load_payload(path, StoryDraftPayload, "story")


def load_character(path: Path) -> CharacterDraftPayload:
    return _load_payload(path, CharacterDraftPayload, "character")


def load_stories(directory: Path = STORIES_DIR) -> list[SeedStory]:
    return [SeedStory(slug=path.stem, payload=load_story(path)) for path in _json_files(directory)]


def load_characters(directory: Path = CHARACTERS_DIR) -> list[SeedCharacter]:
    return [
        SeedCharacter(slug=path.stem, payload=load_character(path))
        for path in _json_files(directory)
    ]


def _json_files(directory: Path) -> list[Path]:
    """slug 순으로 정렬해 돌려준다 — 데이터 파일이 하나도 없으면 빈 목록."""
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def _load_payload(path: Path, model: type[PayloadT], kind: str) -> PayloadT:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeedContentError(f"{path.name}: JSON 을 읽지 못했다 — {exc}") from exc
    if not isinstance(raw, dict):
        raise SeedContentError(f"{path.name}: 최상위가 JSON 객체가 아니다")

    _fill_entity_ids(raw, f"{kind}:{path.stem}")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise SeedContentError(f"{path.name}: {model.__name__} 스키마에 맞지 않는다 — {exc}") from exc


def _fill_entity_ids(node: dict[str, Any], path: str) -> None:
    """리스트 안의 객체마다 위치 기반 결정적 id 를 채운다(이미 있으면 손대지 않는다)."""
    for key, value in node.items():
        if not isinstance(value, list):
            continue
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue  # hashtags / triggerKeywords 같은 문자열 리스트
            item_path = f"{path}:{key}[{index}]"
            item.setdefault("id", str(seed_uuid(item_path)))
            _fill_entity_ids(item, item_path)
