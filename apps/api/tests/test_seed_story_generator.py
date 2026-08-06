"""`scripts/generate_seed_stories.py` 의 조립·검증·재시도 (US-013).

Gemini 호출 자체는 테스트하지 않는다 — 생성기가 (a) 매트릭스의 확정 콘셉트를 그대로 박아
넣는지, (b) 시드가 실제로 거는 관문을 파일로 쓰기 **전에** 통과시키는지, (c) 걸렸을 때 그
이유를 프롬프트에 되먹여 다시 부르는지를 고정한다.
"""

from collections.abc import AsyncIterator
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

import generate_seed_stories
from api.llm.client import LLMClient, LLMClientError
from generate_seed_stories import (
    MAX_ATTEMPTS,
    GeneratedEnding,
    GeneratedEndingRule,
    GeneratedKeywordNote,
    GeneratedShortcut,
    GeneratedStartingSetup,
    GeneratedStatDef,
    GeneratedStory,
    assemble_story,
    build_prompt,
    stat_display_name,
    validate_story,
)
from seed_content.loader import parse_story
from seed_content.matrix import MatrixSlot, load_matrix

T = TypeVar("T", bound=BaseModel)

SLOT_SLUG = "romance-lockedwith"  # 시작설정 2개 · 스탯 3개 · 추리/밀실


@pytest.fixture
def slot() -> MatrixSlot:
    return next(item for item in load_matrix() if item.slug == SLOT_SLUG)


def _story(slot: MatrixSlot, **overrides: Any) -> GeneratedStory:
    """검증을 통과하는 최소 생성물. 개별 테스트가 필드 하나씩 망가뜨린다."""
    names = [stat_display_name(stat) for stat in slot.stats]
    setups = [
        GeneratedStartingSetup(
            name=text[:12],
            prologue=f"{text} 그리고 당신은 문 앞에 서 있다.",
            opening_message="…여기서 뭐 하십니까.",
            playguide="상대의 의심을 낮추면서 우위를 챙기세요.",
            suggested_replies=["문 좀 열어봐요", "그 서류 뭐예요?", "오늘은 그만하죠"],
            stat_defs=[
                GeneratedStatDef(
                    name=name,
                    icon="Heart",
                    color="rose",
                    min_value=0,
                    max_value=100,
                    initial_value=30,
                    unit="",
                    description=f"{name} 은 근거를 댈 때 오르고 말을 바꾸면 내려간다.",
                )
                for name in names
            ],
            endings=[
                GeneratedEnding(
                    name=f"{text[:6]} 엔딩 {index}",
                    turn_count_gate=12,
                    judgment_prompt="상대가 증거를 스스로 내밀었는가?",
                    epilogue="문이 열렸고, 복도는 비어 있었다.",
                    hint="끝까지 밀어붙이면",
                    stat_rule_logic="and",
                    stat_rules=[GeneratedEndingRule(stat=names[0], operator="gte", threshold=80)],
                )
                for index in (1, 2)
            ],
        )
        for text in slot.starting_setups
    ]
    payload: dict[str, Any] = {
        "setting_text": "당신은 이 이야기의 서술자다. 응답 앞에 화자 라벨을 붙이지 않는다.",
        "development_example": "사용자: 문 열려요?\n서술자: (손잡이가 헛돈다) 안 열립니다.",
        "description": "심리 전날 밤, 자료실에 갇힌 두 대리인의 하룻밤.",
        "hashtags": ["혐관", "밀실", "법정"],
        "starting_setups": setups,
        "keyword_notes": [
            GeneratedKeywordNote(info_text=f"메모 {index}", trigger_keywords=[f"단서{index}"])
            for index in range(4)
        ],
        "shortcuts": [
            GeneratedShortcut(name=f"행동 {index}", description="설명", prompt="지시")
            for index in range(2)
        ],
    }
    payload.update(overrides)
    return GeneratedStory(**payload)


class FakeLLMClient(LLMClient):
    """정해진 결과를 순서대로 돌려주고 받은 프롬프트를 기록한다."""

    def __init__(self, results: list[GeneratedStory | LLMClientError]) -> None:
        self.results = results
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> AsyncIterator[str]:  # pragma: no cover - 미사용
        raise NotImplementedError

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
    ) -> T:
        self.prompts.append(prompt)
        result = self.results.pop(0)
        if isinstance(result, LLMClientError):
            raise result
        assert isinstance(result, response_schema)
        return result


def test_stat_display_name_strips_the_design_note() -> None:
    assert stat_display_name("남은 방송 회차(30→0)") == "남은 방송 회차"
    assert stat_display_name("산소·전력(자원)") == "산소·전력"
    assert stat_display_name("의심") == "의심"


def test_assemble_pins_the_fixed_concept(slot: MatrixSlot) -> None:
    """제목/한줄/타겟/장르는 LLM 출력 스키마에 아예 없고 매트릭스에서 온다."""
    raw = assemble_story(slot, _story(slot))

    assert raw["name"] == slot.title
    assert raw["oneLiner"] == slot.one_liner
    assert raw["target"] == slot.target
    assert raw["genreId"] == str(slot.genre_id)
    assert raw["visibility"] == "public"
    assert raw["thumbnailAssetId"] is None  # 시드 실행 시점에 채워진다
    assert raw["promptTemplate"] == "basic"  # 플레이 동사 '추리'
    assert len(raw["startingSetups"]) == len(slot.starting_setups)


def test_assemble_resolves_color_names_and_keeps_json_uuid_free(slot: MatrixSlot) -> None:
    raw = assemble_story(slot, _story(slot))
    stat = raw["startingSetups"][0]["statDefs"][0]

    assert stat["color"] == "oklch(0.62 0.19 350)"  # 'rose'
    assert stat["unit"] is None  # 빈 문자열은 null 로
    assert "id" not in stat
    assert raw["keywordNotes"][0]["startingSetupId"] is None


def test_assemble_links_multiple_rules_with_one_logic(slot: MatrixSlot) -> None:
    """`nextOp` 은 규칙 사이에만 붙는다 — 마지막 규칙에 붙으면 평가가 어긋난다."""
    names = [stat_display_name(stat) for stat in slot.stats]
    story = _story(slot)
    story.starting_setups[0].endings[0].stat_rules = [
        GeneratedEndingRule(stat=names[0], operator="gte", threshold=80),
        GeneratedEndingRule(stat=names[1], operator="lte", threshold=20),
    ]

    rules = assemble_story(slot, story)["startingSetups"][0]["endings"][0]["statRules"]

    assert rules[0]["nextOp"] == "and"
    assert "nextOp" not in rules[1]
    assert rules[0]["stat"] == names[0]  # UUID 가 아니라 이름 참조


def test_valid_story_passes_the_seed_gate(slot: MatrixSlot) -> None:
    assert validate_story(slot, assemble_story(slot, _story(slot))) == []


def test_parse_story_does_not_leak_ids_into_the_file(slot: MatrixSlot) -> None:
    """검증이 채우는 파생 id 가 원본 dict 에 남으면 커밋되는 JSON 에 UUID 가 새어 나간다."""
    raw = assemble_story(slot, _story(slot))
    parse_story(raw, slot.slug)

    assert "id" not in raw["startingSetups"][0]
    assert "statId" not in raw["startingSetups"][0]["endings"][0]["statRules"][0]


def test_rejects_renamed_stats(slot: MatrixSlot) -> None:
    story = _story(slot)
    story.starting_setups[0].stat_defs[1].name = "내 마음대로 바꾼 스탯"

    errors = validate_story(slot, assemble_story(slot, story))

    assert any("스탯 이름" in error for error in errors)


def test_rejects_unknown_stat_reference(slot: MatrixSlot) -> None:
    story = _story(slot)
    story.starting_setups[0].endings[0].stat_rules[0].stat = "없는 스탯"

    errors = validate_story(slot, assemble_story(slot, story))

    assert any("없는 스탯" in error for error in errors)


def test_rejects_threshold_outside_the_stat_range(slot: MatrixSlot) -> None:
    story = _story(slot)
    story.starting_setups[0].endings[0].stat_rules[0].threshold = 500

    errors = validate_story(slot, assemble_story(slot, story))

    assert any("영영 도달할 수 없다" in error for error in errors)


def test_rejects_rules_already_true_at_initial_values(slot: MatrixSlot) -> None:
    story = _story(slot)
    story.starting_setups[0].endings[0].stat_rules[0].threshold = 10  # 초기값 30 >= 10

    errors = validate_story(slot, assemble_story(slot, story))

    assert any("스탯이 하나도 안 움직여도" in error for error in errors)


def test_rejects_low_turn_count_gate(slot: MatrixSlot) -> None:
    story = _story(slot)
    story.starting_setups[0].endings[0].turn_count_gate = 5

    errors = validate_story(slot, assemble_story(slot, story))

    assert any("turnCountGate" in error for error in errors)


def test_rejects_too_few_keyword_notes(slot: MatrixSlot) -> None:
    story = _story(slot)
    story.keyword_notes = story.keyword_notes[:2]

    errors = validate_story(slot, assemble_story(slot, story))

    assert any("keywordNotes" in error for error in errors)


def test_rejects_wrong_starting_setup_count(slot: MatrixSlot) -> None:
    story = _story(slot)
    story.starting_setups = story.starting_setups[:1]

    errors = validate_story(slot, assemble_story(slot, story))

    assert any("시작 상황이" in error for error in errors)


def test_prompt_carries_concept_rating_and_previous(slot: MatrixSlot) -> None:
    prompt = build_prompt(slot, ["- 「앞 스토리」(romance-3rdloop) — 요약"])

    assert slot.title in prompt
    assert slot.one_liner in prompt
    assert slot.forbidden[0] in prompt
    assert "선정성" in prompt  # §6 수위 규칙
    assert "겹치면 안 된다" in prompt
    assert "romance-3rdloop" in prompt


def test_prompt_feeds_validation_errors_back(slot: MatrixSlot) -> None:
    prompt = build_prompt(slot, [], ["엔딩 임계값이 범위 밖이다"])

    assert "엔딩 임계값이 범위 밖이다" in prompt


async def test_retries_until_the_story_validates(slot: MatrixSlot) -> None:
    broken = _story(slot)
    broken.starting_setups[0].endings[0].turn_count_gate = 5
    client = FakeLLMClient([broken, _story(slot)])

    raw = await generate_seed_stories._generate_slot(client, slot, [])

    assert raw is not None
    assert len(client.prompts) == 2
    assert "turnCountGate" in client.prompts[1]  # 실패 이유가 되먹여졌다


async def test_gives_up_after_max_attempts(slot: MatrixSlot) -> None:
    broken = _story(slot)
    broken.keyword_notes = []
    client = FakeLLMClient([broken] * MAX_ATTEMPTS)

    assert await generate_seed_stories._generate_slot(client, slot, []) is None
    assert len(client.prompts) == MAX_ATTEMPTS


async def test_transient_call_failure_is_retried(slot: MatrixSlot) -> None:
    client = FakeLLMClient([LLMClientError(""), _story(slot)])

    assert await generate_seed_stories._generate_slot(client, slot, []) is not None
    assert len(client.prompts) == 2
