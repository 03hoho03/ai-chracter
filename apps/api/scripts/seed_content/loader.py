"""시드 콘텐츠 데이터 파일 로더.

파일 하나 = 콘텐츠 하나이고 파일명(확장자 제외)이 곧 slug 다:

    data/tutorial/stories/{slug}.json      -> StoryDraftPayload
    data/tutorial/characters/{slug}.json   -> CharacterDraftPayload

저장소에 든 시드는 제작 가이드가 단계마다 예시로 인용하는 튜토리얼 작품뿐이다. 발행 불변식처럼
모든 시드에 걸리는 검사와 `seed_dev` 는 `load_all_*()`·`*_DIRS` 를 돌아, 시드 폴더가 늘어도
같은 목록 하나만 고치면 된다.

JSON 은 API 요청 바디와 같은 camelCase 이며 기존 draft 스키마 그대로 검증한다 — 시드
전용 스키마를 따로 두지 않는다. 그래야 빌더 API 가 받는 것과 같은 모양임이 보장되고,
스키마가 바뀌면 시드가 조용히 어긋나는 대신 파일명을 담은 에러로 죽는다.

**엔티티 id 는 JSON 에 적지 않는다.** 리스트 안의 객체마다 파일 안에서의 위치
(`story:tutorial-filmclub:startingSetups[0]:endings[1]`)로 `seed_uuid` 를 파생해 채우므로
사람이 UUID 를 쓸 필요가 없다. 대신 위치가 곧 id 라, 이미 시드된 콘텐츠의 리스트
**중간에** 항목을 끼워 넣으면 그 뒤 항목들의 id 가 전부 밀린다 — 새 항목은 뒤에 붙일 것.
JSON 이 `id` 를 직접 적어두면 그 값을 그대로 존중한다.

이 규칙 때문에 다른 항목의 id 를 참조해야 하는 필드(`keywordNotes[].startingSetupId`)는
손으로 쓸 수 없다 — 그런 키워드북은 `null`(스토리 전체 적용)로 두거나, 참조가 정말
필요해지면 그때 upsert 쪽에서 풀어야 한다.

**엔딩 규칙과 상황 노트 조건의 `statId` 만은 예외로 이름으로 쓴다.** 그 참조는 `null` 로 둘 수
없고(엔딩이 조용히 안 열리고, 노트가 조용히 안 실린다) 값도 미리 알 수 없으므로, 규칙에
`"stat": "신뢰"` 처럼 같은 시작설정 `statDefs` 의 **이름**을 적으면 여기서 파생 id 로 바꿔
`statId` 를 채운다. 없는 이름이면 파일명을 담은 에러로 죽는다. 상황 노트는
`startingSetups[].situationNotes[].conditionRules[]` 에 쓰고, 생략해도 된다.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from api.content.schemas import CharacterDraftPayload, StoryDraftPayload

from .ids import seed_uuid

DATA_DIR = Path(__file__).parent / "data"
TUTORIAL_STORIES_DIR = DATA_DIR / "tutorial" / "stories"
TUTORIAL_CHARACTERS_DIR = DATA_DIR / "tutorial" / "characters"
# 시드 폴더 목록의 단일 소스 — 로더를 거치는 검사와 원문 JSON 을 직접 읽는 검사가 같은 목록을
# 돌아야 한쪽만 새 폴더를 보는 일이 없다.
STORY_DIRS = (TUTORIAL_STORIES_DIR,)
CHARACTER_DIRS = (TUTORIAL_CHARACTERS_DIR,)
# 운영에서 읽기 전용으로 내보낸 비공개 시드 묶음 자리(gitignore — 저장소는 공개라 커밋하지 않는다). 안에
# `stories/*.json`·`characters/*.json`·`images/`·`manifest.json` 을 둔다. 작품 JSON 이 하나라도 있으면
# 시드는 이 묶음만 넣고 튜토리얼은 넣지 않는다. 테스트가 바꿔 끼울 수 있게 호출할 때 이 이름을 읽는다.
PRIVATE_DIR = Path(__file__).parent / "private"

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class SeedContentError(Exception):
    """데이터 파일 하나를 읽거나 검증하는 데 실패했다 — 메시지에 항상 파일명이 들어간다."""


@dataclass(frozen=True)
class SeedStory:
    slug: str
    payload: StoryDraftPayload
    # JSON 최상위 `seedPublished` (없으면 발행). 모델이 모르는 키라 검증은 무시하고 로더가 따로 읽는다 — 거짓이면
    # 시드가 초안만 만들고 발행 검증·발행을 건너뛴다.
    published: bool = True


@dataclass(frozen=True)
class SeedCharacter:
    slug: str
    payload: CharacterDraftPayload
    # `SeedStory.published` 와 같다.
    published: bool = True


def load_story(path: Path) -> StoryDraftPayload:
    return _load_payload(path, StoryDraftPayload, "story", _resolve_stat_refs)


def load_character(path: Path) -> CharacterDraftPayload:
    return _load_payload(path, CharacterDraftPayload, "character")


def load_stories(directory: Path) -> list[SeedStory]:
    return [SeedStory(slug=path.stem, payload=load_story(path)) for path in _json_files(directory)]


def load_characters(directory: Path) -> list[SeedCharacter]:
    return [
        SeedCharacter(slug=path.stem, payload=load_character(path))
        for path in _json_files(directory)
    ]


def load_all_stories() -> list[SeedStory]:
    return [story for directory in STORY_DIRS for story in load_stories(directory)]


def load_all_characters() -> list[SeedCharacter]:
    return [
        character for directory in CHARACTER_DIRS for character in load_characters(directory)
    ]


def load_seed_stories(private_dir: Path | None = None) -> list[SeedStory]:
    """시드할 스토리 목록. 비공개 묶음(`private_dir`, 생략하면 `PRIVATE_DIR`)에 작품 JSON 이 하나라도 있으면 그
    묶음의 `stories/` 만, 없거나 비었으면 튜토리얼 목록이다. 판정은 스토리·캐릭터를 합쳐 하므로 묶음에 캐릭터만
    있으면 스토리는 빈 목록이다."""
    # 아직 비공개 묶음을 읽지 않는다 — 늘 튜토리얼 목록.
    return load_all_stories()


def load_seed_characters(private_dir: Path | None = None) -> list[SeedCharacter]:
    """시드할 캐릭터 목록. 고르는 규칙은 `load_seed_stories` 와 같다."""
    # 아직 비공개 묶음을 읽지 않는다 — 늘 튜토리얼 목록.
    return load_all_characters()


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
    """엔딩 규칙·상황 노트 조건이 이름으로 가리킨 스탯(`stat`)과 엔딩의 우선 스탯(`priorityStat`)을 같은 시작설정의
    파생 id(`statId`·`priorityStatId`)로 바꾼다."""
    for setup in _dict_items(raw.get("startingSetups")):
        stat_ids = {
            stat["name"]: stat["id"]
            for stat in _dict_items(setup.get("statDefs"))
            if "name" in stat and "id" in stat
        }
        for ending in _dict_items(setup.get("endings")):
            _fill_rule_list_stat_ids(ending.get("statRules"), stat_ids, filename, "엔딩 규칙")
            _fill_priority_stat_id(ending, stat_ids, filename)
        for note in _dict_items(setup.get("situationNotes")):
            _fill_rule_list_stat_ids(note.get("conditionRules"), stat_ids, filename, "상황 노트 조건")


def _fill_rule_list_stat_ids(items: Any, stat_ids: dict[str, str], filename: str, owner_label: str) -> None:
    for item in _dict_items(items):
        rules = _dict_items(item.get("rules")) if item.get("kind") == "group" else [item]
        for rule in rules:
            _fill_stat_id(rule, stat_ids, filename, owner_label)


def _fill_stat_id(rule: dict[str, Any], stat_ids: dict[str, str], filename: str, owner_label: str) -> None:
    name = rule.get("stat")
    if name is None or "statId" in rule:
        return
    if name not in stat_ids:
        raise SeedContentError(
            f"{filename}: {owner_label}이 같은 시작설정에 없는 스탯 '{name}' 을 가리킨다 "
            f"— 쓸 수 있는 이름: {sorted(stat_ids)}"
        )
    rule["statId"] = stat_ids[name]


def _fill_priority_stat_id(ending: dict[str, Any], stat_ids: dict[str, str], filename: str) -> None:
    """`priorityStat` 을 적지 않은 엔딩은 `priorityStatId` 도 적지 않은 채로 둔다 — 저장이 그 엔딩의 기존 값을 건드리지
    않는다(`EndingDraftItem` docstring). `null` 로 적으면 비운다. 모델이 모르는 키라 그대로 두면 조용히 버려지므로 뺀다."""
    if "priorityStat" not in ending:
        return
    name = ending.pop("priorityStat")
    if "priorityStatId" in ending:
        return
    if name is None:
        ending["priorityStatId"] = None
        return
    if name not in stat_ids:
        raise SeedContentError(
            f"{filename}: 엔딩 우선 스탯이 같은 시작설정에 없는 스탯 '{name}' 을 가리킨다 "
            f"— 쓸 수 있는 이름: {sorted(stat_ids)}"
        )
    ending["priorityStatId"] = stat_ids[name]


def _dict_items(value: Any) -> list[dict[str, Any]]:
    """리스트 안의 객체만 골라 돌려준다 — 모양이 어긋난 값은 pydantic 검증이 잡는다."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
