"""관계·사실 기억 문안의 렌더 — 추출 호출 프롬프트(`build_memory_fact_prompt`), 생성 프롬프트에서 사실 섹션의 자리, 어드민
미리보기.

세트는 `_migrated_schema`가 심은 활성 세트를 `load_active_prompt_set`으로 읽는다. 추출 프롬프트의 기대값은 측정 하네스가 사실
추출 문안을 다듬을 때 쓴 조립 모양(지시문 → 이름 한 줄 → `[기존 키]` 줄 또는 "(없음)" → 줄 번호를 붙인 접힌 대화, 사이는 빈 줄
하나)을 이 파일에 직접 적은 것이다 — 운영 렌더가 그 모양과 바이트까지 같아야 측정 수치가 운영에 그대로 옮겨진다.

생성 프롬프트에 사실 값을 넘기는 호출부는 아직 없어서, 자리는 렌더 함수에 값을 직접 넣어 본다."""

import importlib.util
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import (
    ALLOWED_PLACEHOLDERS,
    PromptLane,
    PromptNames,
    build_memory_fact_prompt,
    load_active_prompt_set,
    render_prompt_channel,
)
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection
from api.llm.chat_models import PromptSetModelId
from factories import _create_admin, _login_as_admin

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("5cab2abe4e7b")
_NAMES = PromptNames(persona_name="하늘", char_name="민지")
_NO_NAMES = PromptNames(persona_name=None, char_name=None)
_EXISTING = ["relation|민지|하늘 = 경계 — 말을 아낌 (confirmed)", "fact|민지|생일 달 = 삼월 (claimed)"]
_FACT_LINES = "- 민지 → 사용자: 경계를 풀었다\n- 민지: 겨울 오디션 준비 (사용자만 앎)"
_RECALL_LINES = "- 빵집 약속: 토요일 열한 시에 소금빵을 사 오기로 했다. (인물의 말)"


def _window() -> list[ChatMessage]:
    """사용자 줄과 모델 줄을 섞는다 — 모델 줄은 미디어 태그를 지우고 `{{user}}` 를 바꾸고, 사용자 줄은 그대로다."""
    return [
        ChatMessage(role=ChatMessageRole.USER, content="빵집 가자 {{user}}"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="{{user}}, 좋아.{{img::민아/창가}} 소금빵 사 올게."),
        ChatMessage(role=ChatMessageRole.USER, content="토요일 열한 시에"),
    ]


def _harness_prompt(user_name: str, existing: list[str], turn_lines: str) -> str:
    parts = [_M.FACT_INSTRUCTION_BODY.strip()]
    if user_name:
        parts.append(f"사용자의 이야기 속 이름: {user_name}")
    parts.append("[기존 키]\n" + ("\n".join(existing) if existing else "(없음)"))
    parts.append("[접힌 대화]\n" + turn_lines)
    return "\n\n".join(parts)


# ---- 추출 호출 프롬프트 ------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["gemini", "haiku"])
@pytest.mark.parametrize("lane", ["story", "character"])
async def test_fact_prompt_has_the_layout_the_harness_measured(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    is_story = lane == "story"
    assistant = prompt_set.story_assistant_label if is_story else prompt_set.character_assistant_label

    prompt = build_memory_fact_prompt(
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=is_story,
        existing_facts=_EXISTING,
        turns=_window(),
        names=_NAMES,
    )

    turn_lines = (
        f"[1] {prompt_set.user_label}: 빵집 가자 {{{{user}}}}\n"
        f"[2] {assistant}: 하늘, 좋아. 소금빵 사 올게.\n"
        f"[3] {prompt_set.user_label}: 토요일 열한 시에"
    )
    assert prompt == _harness_prompt("하늘", _EXISTING, turn_lines)


async def test_first_window_still_carries_the_existing_keys_header_with_none(db_session: AsyncSession) -> None:
    """첫 구간에는 기존 키가 없어도 머리글과 "(없음)"이 실린다(하네스와 같다). 이름이 없으면 이름 한 줄만 빠진다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")

    prompt = build_memory_fact_prompt(
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=True,
        existing_facts=[],
        turns=_window()[:1],
        names=_NO_NAMES,
    )

    assert prompt == _harness_prompt("", [], f"[1] {prompt_set.user_label}: 빵집 가자 {{{{user}}}}")


# ---- 생성 프롬프트의 사실 섹션 ----------------------------------------------------------------


def _body(sections: list[PromptSection], slot: str) -> str:
    bodies = [s.body for s in sections if s.channel == "generation" and s.slot == slot]
    assert len(bodies) == 1, slot
    return bodies[0]


def _generation_values(**overrides: str) -> dict[str, str]:
    """생성 채널이 쓰는 이름 전부에 값을 채운다 — 비면 conditional 섹션이 빠져 자리를 볼 수 없다."""
    names: set[str] = set()
    for (channel, _slot), allowed in ALLOWED_PLACEHOLDERS.items():
        if channel == "generation":
            names |= allowed
    return {**{name: f"<{name}>" for name in names}, **overrides}


_WRITING_PAIRS = [(lane, model) for lane in ("story", "character") for model in ("gemini", "sonnet", "opus")]


@pytest.mark.parametrize(("lane", "model"), _WRITING_PAIRS, ids=[f"{lane}-{model}" for lane, model in _WRITING_PAIRS])
async def test_facts_section_renders_after_history_and_before_recall(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """사실과 회상 값이 둘 다 있으면 대화 기록 → 관계와 사실 → 지난 기억 순서로 붙어 나온다."""
    _prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    values = _generation_values(
        history_lines="대화 줄", memory_fact_lines=_FACT_LINES, memory_recall_lines=_RECALL_LINES
    )

    rendered = render_prompt_channel(sections, channel="generation", scope=lane, values=values)

    expected_run = "\n\n".join(
        [
            _body(sections, "history").format(history_lines="대화 줄"),
            _body(sections, "memory_facts").format(memory_fact_lines=_FACT_LINES),
            _body(sections, "memory_recall").format(memory_recall_lines=_RECALL_LINES),
        ]
    )
    assert expected_run in rendered
    assert rendered.count(_FACT_LINES) == 1


async def test_facts_section_drops_when_there_are_no_fact_lines(db_session: AsyncSession) -> None:
    """사실 값을 넘기지 않는 지금의 호출부에서는 섹션째 빠져 생성 프롬프트가 이 리비전 전과 같다."""
    _prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    header = _M.FACTS_BODY.partition("\n")[0]

    rendered = render_prompt_channel(
        sections, channel="generation", scope="story", values=_generation_values(memory_fact_lines="")
    )

    assert header + "\n" not in rendered


# ---- 어드민 미리보기 --------------------------------------------------------------------------


async def _preview(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str, model: str
) -> list[dict[str, str]]:
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin)
    resp = await db_client.post(f"/admin/prompt-sets/{lane}/draft/preview", params={"model": model})
    assert resp.status_code == 200
    items: list[dict[str, str]] = resp.json()["items"]
    return items


@pytest.mark.parametrize("model", ["gemini", "sonnet", "opus", "haiku"])
@pytest.mark.parametrize("lane", ["story", "character"])
async def test_preview_shows_the_fact_prompt_with_every_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str, model: str
) -> None:
    """운영자가 사실 추출 문안을 고친 뒤 결과를 볼 수 있어야 한다 — 이름 한 줄과 기존 키까지 샘플로 채운다."""
    items = await _preview(db_client, db_session, lane, model)

    fact = [item for item in items if item["channel"] == "memory_fact"]
    assert len(fact) == 1
    text = fact[0]["text"]
    assert text.startswith(_M.FACT_INSTRUCTION_BODY + "\n\n사용자의 이야기 속 이름: [샘플] 하늘\n\n[기존 키]\n")
    assert "[기존 키]\n(없음)" not in text
    assert "\n\n[접힌 대화]\n[1] " in text


@pytest.mark.parametrize("model", ["gemini", "sonnet", "opus"])
@pytest.mark.parametrize("lane", ["story", "character"])
async def test_generation_preview_shows_the_facts_section_before_the_recall_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str, model: str
) -> None:
    """사실 섹션도 샘플 줄로 채워 머리글과 꼬리표 설명이 보이게 한다. 다른 채널 항목에는 없다."""
    items = await _preview(db_client, db_session, lane, model)

    facts_header = _M.FACTS_BODY.split("{memory_fact_lines}")[0]
    recall_header = _M.RECALL_BODY.split("{memory_recall_lines}")[0]
    generation = [item for item in items if item["channel"] == "generation"]
    others = [item for item in items if item["channel"] != "generation"]
    assert generation and others
    for item in generation:
        assert item["text"].count(facts_header) == 1
        assert item["text"].index(facts_header) < item["text"].index(recall_header)
    assert all(facts_header not in item["text"] for item in others)
