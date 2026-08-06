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

**엔딩 규칙의 `statId` 만은 예외로 이름으로 쓴다.** 그 참조는 `null` 로 둘 수 없고(엔딩이
조용히 안 열린다) 값도 미리 알 수 없으므로, 규칙에 `"stat": "신뢰"` 처럼 같은 시작설정
`statDefs` 의 **이름**을 적으면 여기서 파생 id 로 바꿔 `statId` 를 채운다. 없는 이름이면
파일명을 담은 에러로 죽는다.
"""

import copy
import json
from collections.abc import Callable
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
    return _load_payload(path, StoryDraftPayload, "story", _resolve_stat_refs)


def load_character(path: Path) -> CharacterDraftPayload:
    return _load_payload(path, CharacterDraftPayload, "character")


def parse_story(raw: dict[str, Any], slug: str) -> StoryDraftPayload:
    """아직 파일이 아닌 JSON 객체를 `load_story` 와 똑같은 규칙으로 검증한다(배치 생성기용).

    생성기가 만든 dict 를 **쓰기 전에** 통과시키려는 것이라 경로 대신 slug 를 받는다 — id
    파생 경로와 에러 메시지가 실제로 저장될 파일과 같아야 한다. 인자는 건드리지 않는다
    (검증 과정에서 채워지는 id 가 파일에 새어 나가면 "시드 JSON 에 UUID 를 쓰지 않는다"는
    규약이 깨진다).
    """
    return _parse_payload(copy.deepcopy(raw), StoryDraftPayload, "story", slug, _resolve_stat_refs)


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


def _load_payload(
    path: Path,
    model: type[PayloadT],
    kind: str,
    resolve_refs: Callable[[dict[str, Any], str], None] | None = None,
) -> PayloadT:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeedContentError(f"{path.name}: JSON 을 읽지 못했다 — {exc}") from exc
    if not isinstance(raw, dict):
        raise SeedContentError(f"{path.name}: 최상위가 JSON 객체가 아니다")
    return _parse_payload(raw, model, kind, path.stem, resolve_refs)


def _parse_payload(
    raw: dict[str, Any],
    model: type[PayloadT],
    kind: str,
    slug: str,
    resolve_refs: Callable[[dict[str, Any], str], None] | None,
) -> PayloadT:
    filename = f"{slug}.json"
    _fill_entity_ids(raw, f"{kind}:{slug}")
    if resolve_refs is not None:
        resolve_refs(raw, filename)
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise SeedContentError(f"{filename}: {model.__name__} 스키마에 맞지 않는다 — {exc}") from exc


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


def _resolve_stat_refs(raw: dict[str, Any], filename: str) -> None:
    """엔딩 규칙이 이름으로 가리킨 스탯(`stat`)을 같은 시작설정의 파생 id(`statId`)로 바꾼다."""
    for setup in _dict_items(raw.get("startingSetups")):
        stat_ids = {
            stat["name"]: stat["id"]
            for stat in _dict_items(setup.get("statDefs"))
            if "name" in stat and "id" in stat
        }
        for ending in _dict_items(setup.get("endings")):
            for item in _dict_items(ending.get("statRules")):
                rules = _dict_items(item.get("rules")) if item.get("kind") == "group" else [item]
                for rule in rules:
                    _fill_stat_id(rule, stat_ids, filename)


def _fill_stat_id(rule: dict[str, Any], stat_ids: dict[str, str], filename: str) -> None:
    name = rule.get("stat")
    if name is None or "statId" in rule:
        return
    if name not in stat_ids:
        raise SeedContentError(
            f"{filename}: 엔딩 규칙이 같은 시작설정에 없는 스탯 '{name}' 을 가리킨다 "
            f"— 쓸 수 있는 이름: {sorted(stat_ids)}"
        )
    rule["statId"] = stat_ids[name]


def _dict_items(value: Any) -> list[dict[str, Any]]:
    """리스트 안의 객체만 골라 돌려준다 — 모양이 어긋난 값은 pydantic 검증이 잡는다."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
