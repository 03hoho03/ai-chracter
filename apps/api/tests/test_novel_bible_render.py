"""정본 기억 채널 렌더의 필수 값 검사.

조건부(`conditional`)가 아닌 값 섹션은 그 슬롯이 늘 있어야 하는 입력이다. 그 값이 비면 렌더가 머리글만 남은 본문을 "비지 않은
결과"로 내보내므로, 렌더가 값을 채우기 전에 따로 보고 `PromptRenderError` 로 멈춘다. 규칙은 채널·슬롯 이름을 모른다 — 문안의
조건부 표시만 본다."""

import uuid

import pytest

from api.chat.prompt_builder import PromptRenderError
from api.db.models.prompt import PromptSection
from api.novel_bible.core.contracts import PromptSource
from api.novel_bible.core.render import render

_CHANNEL = "synthetic_bible_channel"


def _source(*slots: tuple[str, str, bool], scope: str = "both") -> PromptSource:
    set_id = uuid.uuid4()
    return PromptSource(
        prompt_set_id=set_id,
        sections=[
            PromptSection(
                prompt_set_id=set_id, channel=_CHANNEL, scope=scope if slot != "instruction" else "both", slot=slot,
                variant="", body=body, conditional=conditional, order=order,
            )
            for order, (slot, body, conditional) in enumerate(slots)
        ],
    )


_SLOTS = (
    ("instruction", "합성 지시문", False),
    ("body_text", "[본문]\n{body_text}", False),
    ("hint", "[힌트]\n{hint}", True),
)


def test_a_required_and_an_optional_value_render_together() -> None:
    rendered = render(_source(*_SLOTS), channel=_CHANNEL, scope="story", values={"body_text": "가", "hint": "나"})

    assert rendered.system_instruction == "합성 지시문"
    assert rendered.prompt == "[본문]\n가\n\n[힌트]\n나"


def test_an_empty_optional_value_drops_only_its_section() -> None:
    rendered = render(_source(*_SLOTS), channel=_CHANNEL, scope="story", values={"body_text": "가", "hint": ""})

    assert rendered.prompt == "[본문]\n가"


@pytest.mark.parametrize("value", ["", "   \n\t"], ids=["empty", "whitespace"])
def test_an_empty_required_value_is_a_render_error(value: str) -> None:
    """깨지는 시나리오: 원고가 빈 글로 와도 머리글만 남은 본문이 "비지 않은 결과"로 모델에 나가, 오류 대신 빈 추출이 확정된다."""
    with pytest.raises(PromptRenderError, match="body_text"):
        render(_source(*_SLOTS), channel=_CHANNEL, scope="story", values={"body_text": value, "hint": "나"})


def test_a_missing_required_value_is_a_render_error() -> None:
    with pytest.raises(PromptRenderError, match="body_text"):
        render(_source(*_SLOTS), channel=_CHANNEL, scope="story", values={"hint": "나"})


def test_the_rule_reads_the_conditional_flag_not_the_slot_name() -> None:
    """같은 슬롯이라도 문안이 조건부로 두면 빈 값은 섹션째 빠지고, 조건부가 아니면 오류다 — 규칙이 슬롯 이름 표를 갖지 않는다."""
    optional = _source(("instruction", "합성 지시문", False), ("body_text", "{body_text}", True), ("hint", "{hint}", False))
    rendered = render(optional, channel=_CHANNEL, scope="story", values={"body_text": "", "hint": "나"})
    assert rendered.prompt == "나"

    with pytest.raises(PromptRenderError, match="hint"):
        render(optional, channel=_CHANNEL, scope="story", values={"body_text": "가", "hint": ""})


def test_a_required_section_outside_the_requested_scope_is_not_checked() -> None:
    """다른 원작 종류의 섹션은 렌더되지 않으므로 그 값도 요구하지 않는다."""
    source = _source(
        ("instruction", "합성 지시문", False), ("body_text", "{body_text}", False), ("other", "{other}", False),
        scope="character",
    )
    source = PromptSource(
        prompt_set_id=source.prompt_set_id,
        sections=[
            *[s for s in source.sections if s.slot != "body_text"],
            PromptSection(
                prompt_set_id=source.prompt_set_id, channel=_CHANNEL, scope="both", slot="body_text", variant="",
                body="{body_text}", conditional=False, order=1,
            ),
        ],
    )

    rendered = render(source, channel=_CHANNEL, scope="story", values={"body_text": "가"})

    assert rendered.prompt == "가"
