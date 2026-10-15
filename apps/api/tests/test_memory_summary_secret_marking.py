"""요약 비밀 표기 슬롯 — 스위치(`memory_summary_secret_marking`)가 켜졌을 때만 요약 프롬프트의 지시문 바로 뒤에 비밀 표기 지시와
그 방의 인물 이름 목록이 실린다.

규칙(결과를 보기 전에 적었다):
- 꺼지면 이름 값이 비어 conditional 슬롯이 섹션째 빠진다 — 요약 프롬프트는 이 슬롯이 없는 세트로 렌더한 것과 바이트까지 같다.
- 켜지면 이름 목록을 ", "로 이어 넣는다. 이름이 0개면(첫 접기 — 사실 행이 아직 없고 미디어 북 인물도 없는 방) 고정 문구를
  넣어 슬롯이 늘 실린다.
- 이름 목록 = 호출부가 주는 이름(캐릭터 작품 이름·미디어 북 인물) → 방 사실 행(주어, 관계의 대상, 말한 사람, 아는 사람 원소)
  순으로, 처음 나온 표기를 그대로 지킨다. 같은 이름인지·사용자 표기인지·2자 미만인지는 사실 키와 같은 정규화로 판정한다.
  사실의 속성은 이름이 아니라 넣지 않는다."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_knowledge import room_people, user_names
from api.chat.prompt_builder import (
    NO_ROOM_PEOPLE,
    PromptLane,
    PromptNames,
    build_memory_summary_prompt,
    load_active_prompt_set,
)
from api.content.author_macros import FALLBACK_USER_NAME
from api.db.models import ChatMemoryFact
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection
from factories import PRODUCTION_ENV_NAMES, load_production_env

LABEL = "사용자"
_NAMES = PromptNames(persona_name="하늘", char_name=None)
_SUMMARY = "두 사람은 편의점에서 처음 만났다."


def _row(kind: str = "fact", subject: str = "유나", **extra: object) -> ChatMemoryFact:
    """세션 없이 만든 사실 행 — 이름 목록이 읽는 칸(종류·주어·대상·속성·말한 사람·아는 사람)만 채운다."""
    fields: dict[str, object] = {"kind": kind, "subject": subject, **extra}
    return ChatMemoryFact(**fields)


# ---- 이름 목록(순수 함수) ----------------------------------------------------------------------


def test_room_people_keeps_the_first_spelling_in_source_order() -> None:
    """호출부 이름이 먼저, 사실 행은 쓴 순서와 칸 순서(주어 → 관계 대상 → 말한 사람 → 아는 사람)로. 대소문자·공백만 다른 이름은
    처음 나온 표기 하나로 남는다 — 정규형("mina")이 아니라 원래 표기("Mina")다."""
    rows = [
        _row("relation", "오태민", object="한서윤"),
        _row("fact", "MINA", attribute="생일 달", speaker="  지아 ", known_by=["오태민", "Yuna  Kim"]),
        _row("fact", "yuna kim", attribute="극중 이름"),
    ]

    people = room_people(rows, ["Mina", "한서윤"], users=user_names(None, LABEL))

    assert people == ["Mina", "한서윤", "오태민", "지아", "Yuna  Kim"]


def test_room_people_leaves_out_every_user_form_and_short_names() -> None:
    """사용자 표기(프로필 이름 — 대소문자가 달라도, 대화 줄 라벨, `{{user}}` 대체어, 추출 지시문이 사용자를 부르는 낱말)와 2자
    미만 이름은 빠진다. 사실의 속성·사실 행의 대상 칸은 이름이 아니다."""
    rows = [
        _row("fact", "Sky", attribute="오태민에게 한 약속", object="지아", known_by=["SKY", LABEL, "준"]),
        _row("relation", FALLBACK_USER_NAME, object="사용자 인물", speaker="sKy"),
        _row("relation", "오태민", object="Sky"),
    ]

    people = room_people(rows, ["sky", ""], users=user_names("Sky", LABEL))

    assert people == ["오태민"]


def test_room_people_is_empty_without_names() -> None:
    assert room_people([], [None, ""], users=user_names(None, LABEL)) == []


# ---- 요약 프롬프트 조립 ------------------------------------------------------------------------


def _turns() -> list[ChatMessage]:
    return [
        ChatMessage(role=ChatMessageRole.USER, content="이전 메시지"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="이전 응답"),
    ]


def _body(sections: list[PromptSection], slot: str) -> str:
    return next(s.body for s in sections if s.channel == "memory_summary" and s.slot == slot)


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_switched_off_the_summary_prompt_is_byte_identical_to_a_set_without_the_slot(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """이름 목록을 넘기지 않으면(스위치 꺼짐) 슬롯이 섹션째 빠져, 그 슬롯이 없는 세트로 렌더한 것과 바이트까지 같다. 활성 세트에
    슬롯이 실제로 있는지도 본다 — 없으면 이 비교는 아무것도 증명하지 않는다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane)
    assert any(s.slot == "secret_marking" for s in sections if s.channel == "memory_summary")
    without = [s for s in sections if not (s.channel == "memory_summary" and s.slot == "secret_marking")]

    def build(chosen: list[PromptSection]) -> str:
        return build_memory_summary_prompt(
            prompt_set=prompt_set,
            sections=chosen,
            is_story_chat=lane == "story",
            previous_summary=_SUMMARY,
            turns=_turns(),
            names=_NAMES,
        )

    assert build(sections) == build(without)
    assert "[비밀 표기]" not in build(sections)


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_switched_on_the_slot_follows_the_instruction_with_the_names(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane)
    label = prompt_set.story_assistant_label if lane == "story" else prompt_set.character_assistant_label

    prompt = build_memory_summary_prompt(
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=lane == "story",
        previous_summary=_SUMMARY,
        turns=_turns(),
        names=_NAMES,
        room_people=["오태민", "Mina"],
    )

    turn_lines = f"{prompt_set.user_label}: 이전 메시지\n{label}: 이전 응답"
    assert prompt == "\n\n".join(
        [
            _body(sections, "instruction"),
            _body(sections, "secret_marking").format(room_people="오태민, Mina"),
            _body(sections, "user_name").format(user_name="하늘"),
            _body(sections, "previous_summary").format(previous_summary=_SUMMARY),
            _body(sections, "turn_context").format(turn_lines=turn_lines),
        ]
    )
    assert "- 이 이야기의 인물 이름: 오태민, Mina. 아는 사람을 적을 때" in prompt


async def test_switched_on_without_names_the_slot_still_carries_the_fixed_phrase(db_session: AsyncSession) -> None:
    """이름이 0개인 첫 접기에도 슬롯이 실린다 — 빈 값이면 conditional 로 빠져 1~30턴의 비밀이 표기 없이 첫 요약에 굳는다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")

    prompt = build_memory_summary_prompt(
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=True,
        previous_summary="",
        turns=_turns(),
        names=PromptNames(persona_name=None, char_name=None),
        room_people=[],
    )

    assert NO_ROOM_PEOPLE == "아직 이름이 정해진 인물 없음 — 대화에 나온 이름이나 호칭을 그대로 쓴다"
    assert prompt.startswith(
        _body(sections, "instruction") + "\n\n" + _body(sections, "secret_marking").format(room_people=NO_ROOM_PEOPLE)
    )


def test_production_env_leaves_the_secret_marking_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영 env 에는 스위치가 없어 꺼진 기본값으로 돈다 — 운영 요약 프롬프트는 이 슬롯이 생기기 전과 같다."""
    assert "MEMORY_SUMMARY_SECRET_MARKING" not in PRODUCTION_ENV_NAMES
    assert not load_production_env(monkeypatch).memory_summary_secret_marking
