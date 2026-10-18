"""장면 기억 문안의 렌더 — 추출 호출 프롬프트(`build_memory_episode_prompt`)와 생성 프롬프트의 회상 섹션 자리, 어드민
미리보기.

세트는 `_migrated_schema`가 심은 활성 세트를 `load_active_prompt_set`으로 읽는다. 추출 프롬프트의 기대값은 오프라인
평가에서 추출 문안을 확정할 때 쓴 조립 모양(지시문 → 이름 한 줄 → 앞 구간 장면 제목 → 줄 번호를 붙인 접힌 대화, 사이는
빈 줄 하나)을 이 파일에 직접 적은 것이다 — 운영 렌더가 그 모양과 바이트까지 같아야 평가 수치가 운영에 그대로 옮겨진다."""

import importlib.util
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import (
    PromptNames,
    build_generation_prompt,
    build_memory_episode_prompt,
    build_story_generation_prompt,
    load_active_prompt_set,
)
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection
from api.db.models.story import StoryPromptTemplate
from factories import _create_admin, _login_as_admin

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# head 의 추출 지시문은 장면 추출 지시문에 아는 인물·말한 인물 규칙을 더한 리비전의 판이다(채널의 슬롯 모양은 장면 채널을 처음
# 심은 리비전 그대로다).
_M = _load("eb8d3cc6d5c2")
# 회상 섹션 문안의 지금 판 — 글을 쓰는 여섯 체인의 활성 세트가 이 리비전의 것이다.
_RECALL = _load("726aad108167")
_NAMES = PromptNames(persona_name="하늘", char_name="민지")
_NO_NAMES = PromptNames(persona_name=None, char_name=None)
_RECALL_LINES = "- 빵집 약속: 토요일 열한 시에 소금빵을 사 오기로 했다. (인물의 말)"


def _window() -> list[ChatMessage]:
    """사용자 줄과 모델 줄을 섞는다 — 모델 줄은 미디어 태그를 지우고 `{{user}}` 를 바꾸고, 사용자 줄은 그대로다."""
    return [
        ChatMessage(role=ChatMessageRole.USER, content="빵집 가자 {{user}}"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="{{user}}, 좋아.{{img::민아/창가}} 소금빵 사 올게."),
        ChatMessage(role=ChatMessageRole.USER, content="토요일 열한 시에"),
    ]


def _prototype_prompt(user_name: str, titles: list[str], turn_lines: str) -> str:
    parts = [_M.EPISODE_INSTRUCTION_BODY.strip()]
    if user_name:
        parts.append(f"사용자의 이야기 속 이름: {user_name}")
    if titles:
        parts.append("[앞 구간의 마지막 장면]\n" + "\n".join(titles))
    parts.append("[접힌 대화]\n" + turn_lines)
    return "\n\n".join(parts)


# ---- 추출 호출 프롬프트 ------------------------------------------------------------------------


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_episode_prompt_has_the_layout_the_offline_evaluation_measured(
    db_session: AsyncSession, lane: str
) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane)  # type: ignore[arg-type]
    is_story = lane == "story"
    assistant = prompt_set.story_assistant_label if is_story else prompt_set.character_assistant_label

    prompt = build_memory_episode_prompt(
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=is_story,
        previous_titles=["빵집 가는 길", "토요일 약속"],
        turns=_window(),
        names=_NAMES,
    )

    turn_lines = (
        f"[1] {prompt_set.user_label}: 빵집 가자 {{{{user}}}}\n"
        f"[2] {assistant}: 하늘, 좋아. 소금빵 사 올게.\n"
        f"[3] {prompt_set.user_label}: 토요일 열한 시에"
    )
    assert prompt == _prototype_prompt("하늘", ["빵집 가는 길", "토요일 약속"], turn_lines)


async def test_first_window_without_a_profile_drops_the_name_and_title_sections(db_session: AsyncSession) -> None:
    """첫 접기에는 앞 구간이 없고, 프로필이 없으면 실을 이름이 없다 — 두 섹션이 머리글째 빠진다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")

    prompt = build_memory_episode_prompt(
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=True,
        previous_titles=[],
        turns=_window()[:1],
        names=_NO_NAMES,
    )

    assert prompt == _prototype_prompt("", [], f"[1] {prompt_set.user_label}: 빵집 가자 {{{{user}}}}")


# ---- 생성 프롬프트의 회상 섹션 ----------------------------------------------------------------


def _body(sections: list[PromptSection], slot: str) -> str:
    return next(s.body for s in sections if s.channel == "generation" and s.slot == slot)


def _history() -> list[ChatMessage]:
    return [
        ChatMessage(role=ChatMessageRole.USER, content="이전 메시지"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="이전 응답"),
    ]


async def test_recall_slot_sits_between_history_and_keyword_notes(db_session: AsyncSession) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")

    prompt = build_story_generation_prompt(
        prompt_set=prompt_set,
        sections=sections,
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관",
        development_examples=[],
        user_goal=None,
        rules=None,
        custom_prompt=None,
        prologue="시작 상황",
        history=_history(),
        user_message="이번 메시지",
        user_persona="",
        memory_note="",
        memory_summary="",
        names=_NO_NAMES,
        keyword_note_texts=["키워드 정보"],
        memory_recall_lines=_RECALL_LINES,
    )

    history_lines = f"{prompt_set.user_label}: 이전 메시지\n{prompt_set.story_assistant_label}: 이전 응답"
    expected_run = "\n\n".join(
        [
            _body(sections, "history").format(history_lines=history_lines),
            _body(sections, "memory_recall").format(memory_recall_lines=_RECALL_LINES),
            _body(sections, "keyword_notes").format(keyword_note_lines="키워드 정보"),
        ]
    )
    assert expected_run in str(prompt)
    assert str(prompt).count(_RECALL_LINES) == 1


async def test_recall_slot_sits_between_history_and_the_final_frame_in_character_chat(db_session: AsyncSession) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane="character")

    prompt = build_generation_prompt(
        prompt_set=prompt_set,
        sections=sections,
        character_prompt="캐릭터 프롬프트",
        example_dialogues=[],
        history=_history(),
        user_message="이번 메시지",
        user_persona="",
        memory_note="",
        memory_summary="",
        names=_NO_NAMES,
        memory_recall_lines=_RECALL_LINES,
    )

    history_lines = f"{prompt_set.user_label}: 이전 메시지\n{prompt_set.character_assistant_label}: 이전 응답"
    final_frame = _body(sections, "final_frame").format(
        user_label=prompt_set.user_label, user_message="이번 메시지", assistant_label=prompt_set.character_assistant_label
    )
    expected_tail = "\n\n".join(
        [
            _body(sections, "history").format(history_lines=history_lines),
            _body(sections, "memory_recall").format(memory_recall_lines=_RECALL_LINES),
            final_frame,
        ]
    )
    assert str(prompt).endswith(expected_tail)


# ---- 어드민 미리보기 --------------------------------------------------------------------------


async def _preview(db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str, model: str) -> list[dict[str, str]]:
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin)
    resp = await db_client.post(f"/admin/prompt-sets/{lane}/draft/preview", params={"model": model})
    assert resp.status_code == 200
    items: list[dict[str, str]] = resp.json()["items"]
    return items


@pytest.mark.parametrize("model", ["gemini", "sonnet", "opus", "haiku"])
@pytest.mark.parametrize("lane", ["story", "character"])
async def test_preview_shows_the_episode_prompt_with_every_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str, model: str
) -> None:
    """운영자가 추출 문안을 고친 뒤 결과를 볼 수 있어야 한다 — 이름 한 줄과 앞 구간 제목까지 샘플로 채운다(비우면 conditional
    드롭으로 그 문안이 안 보인다)."""
    items = await _preview(db_client, db_session, lane, model)

    episode = [item for item in items if item["channel"] == "memory_episode"]
    assert len(episode) == 1
    text = episode[0]["text"]
    assert text.startswith(_M.EPISODE_INSTRUCTION_BODY + "\n\n사용자의 이야기 속 이름: [샘플] 하늘\n\n[앞 구간의 마지막 장면]\n")
    assert "\n\n[접힌 대화]\n[1] " in text


@pytest.mark.parametrize("model", ["gemini", "sonnet", "opus"])
@pytest.mark.parametrize("lane", ["story", "character"])
async def test_generation_preview_shows_the_recall_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str, model: str
) -> None:
    """회상 섹션도 샘플 줄로 채워 머리글과 우선순위 문구가 보이게 한다. 다른 채널 항목에는 없다."""
    items = await _preview(db_client, db_session, lane, model)

    header = _RECALL.RECALL_BODY.split("{memory_recall_lines}")[0]
    generation = [item for item in items if item["channel"] == "generation"]
    others = [item for item in items if item["channel"] != "generation"]
    assert generation and others
    assert all(item["text"].count(header) == 1 for item in generation)
    assert all(header not in item["text"] for item in others)
