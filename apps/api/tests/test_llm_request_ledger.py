"""채팅 턴 하나가 LLM 에 보내는 요청 전부를 장부로 고정한다 — 보내기·수정·재생성 × 스토리·캐릭터, 미리보기 스토리·캐릭터,
상위 모델(sonnet)을 고른 스토리 방의 보내기, 그리고 단축어로 보낸 스토리 턴의 재생성.

장부 한 줄은 요청만 본다(응답 텍스트·토큰 수는 보지 않는다): 부른 메서드, 실제로 간 공급자, 호출 위치, 실린 모델,
사용자·방 귀속 유무, 프롬프트와 지시문의 sha256, 정지 시퀀스, 응답 스키마 이름, 캐시 블록 조각 수와 조각별 sha256.
LLM 클라이언트 자리에 진짜 라우팅 클라이언트를 두고 그 안쪽 두 공급자만 기록하는 가짜로 바꾼다 — 상위 모델 턴의 생성만
Bedrock 으로 가고 판정·요약은 Gemini 로 가는지가 장부의 공급자 칸에 남는다.

프롬프트에 실리는 id(칸·상황 이미지·초안 항목)는 테스트마다 새로 만들어지므로, 해시 전에 처음 나온 순서의 번호로 바꾼다
(같은 id 가 같은 자리에 나오는지는 남는다).

방은 30턴짜리라 보내기·수정·재생성 뒤 요약 접기가 실제로 요약 LLM 을 부른다(접기는 응답 뒤 background 에서 돌고 장부의 끝에
남는다). 엔딩은 게이트 1·5 둘이라 보내기(31턴째)와 수정(30턴째)에서 각각 하나씩 판정 차례가 온다.

측정용 프롬프트 덤프도 켜 두고 생성 덤프 줄의 (방 id 유무, 턴, 고른 모델)을 장부 옆에 남긴다 — 리플레이가 방·턴으로 덤프 줄을
고르므로 경로마다 다른 턴 번호(보내기·수정은 올린 턴, 재생성은 지금 턴, 미리보기는 세션 턴 + 1)가 지켜져야 한다.

기대값은 지금 동작을 기록한 것이다(`fixtures/llm_request_ledger.json`). 다시 뜨는 법은 `factories._assert_characterization`.
"""

import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MemorySummaryResult,
    StatRuleJudgmentResult,
)
from api.chat.prompt_set_cache import ACTIVE_PROMPT_SET_KEY_PREFIX
from api.core.config import settings
from api.core.redis import redis_client
from api.db.models import AssetStatus, ChatMessage, ChatMessageRole, ChatRoom, PromptSection, PromptSet
from api.db.models.story import Shortcut
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient, SegmentedPrompt
from api.llm.routing import RoutingLLMClient
from factories import (
    _add_room_cell_and_endings,
    _add_room_situational_image,
    _allow_chat_premium,
    _assert_characterization,
    _assert_recorded_cases,
    _clear_llm_override,
    _login_as,
    _make_asset,
    _make_chat_turn,
    _make_user,
    _make_user_with_clover_lot,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
    _preview_character_payload,
    _preview_story_payload,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "llm_request_ledger.json"

_ROOM_TURNS = 30
# 보내기는 31턴째(게이트 1 의 차례), 수정은 마지막 사용자 메시지를 고쳐 30턴째(게이트 5 의 차례)다.
_ENDING_GATES = (1, 5)

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _sha(text: str, ids: dict[str, str]) -> str:
    normalized = _UUID.sub(lambda m: ids.setdefault(m.group(0), f"<id{len(ids) + 1}>"), text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class _LedgerLLM(LLMClient):
    """한 공급자 자리의 가짜. 받은 요청을 공용 장부에 남기고, 판정에는 모든 판정이 무언가를 하게 하는 답을 준다(스탯 규칙
    a1 발동, 그림 일치, 엔딩 발동) — 뒤따르는 단계가 실제로 돌아야 그 단계의 요청이 장부에 남는다."""

    def __init__(self, provider: str, ledger: list[dict[str, Any]], ids: dict[str, str], match_id: str | None) -> None:
        self._provider = provider
        self._ledger = ledger
        self._ids = ids
        self._match_id = match_id

    def _record(
        self,
        method: str,
        prompt: str,
        system_instruction: str | None,
        stop_sequences: list[str] | None,
        response_schema: type | None,
        usage: LLMCallContext,
    ) -> None:
        self._ledger.append(
            {
                "method": method,
                "provider": self._provider,
                "callSite": usage.call_site,
                "model": usage.model,
                "hasUser": usage.user_id is not None,
                "hasRoom": usage.room_id is not None,
                "promptSha": _sha(prompt, self._ids),
                "systemSha": _sha(system_instruction, self._ids) if system_instruction is not None else None,
                "stopSequences": stop_sequences,
                "responseSchema": response_schema.__name__ if response_schema is not None else None,
                "segments": (
                    {
                        "count": len(prompt.segments),
                        "shas": [_sha(segment, self._ids) for segment in prompt.segments],
                    }
                    if isinstance(prompt, SegmentedPrompt)
                    else None
                ),
            }
        )

    def _answer(self, response_schema: Any) -> Any:
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=["a1"])
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=True)
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=self._match_id)
        if response_schema is MemorySummaryResult:
            return MemorySummaryResult(summary="요약")
        raise AssertionError(f"예상하지 못한 응답 스키마: {response_schema}")

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self._record("generate", prompt, system_instruction, stop_sequences, None, usage)
        yield "오늘은 "
        yield "비가 와."

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self._record("generate_structured", prompt, None, None, response_schema, usage)
        return self._answer(response_schema)

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: Any, *, system_instruction: str, usage: LLMCallContext
    ) -> Any:
        self._record("generate_structured_with_instruction", prompt, system_instruction, None, response_schema, usage)
        return self._answer(response_schema)


@dataclass(frozen=True)
class _Case:
    method: str
    path: str
    body: dict[str, object] | None
    # 그림 판정이 고를 후보 id(칸·상황 이미지). 그림 판정이 없는 경우는 None.
    match_id: str | None


_Builder = Callable[[httpx.AsyncClient, AsyncSession, pytest.MonkeyPatch], Awaitable[_Case]]


async def _story_room(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[uuid.UUID, str, uuid.UUID]:
    room = await _open_room(db_client, db_session, turns=_ROOM_TURNS, lane="story")
    cell_id = await _add_room_cell_and_endings(db_session, room.room_id, _ENDING_GATES)
    return room.room_id, str(cell_id), room.turns[_ROOM_TURNS][0].id


async def _character_room(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[uuid.UUID, str, uuid.UUID]:
    room = await _open_room(db_client, db_session, turns=_ROOM_TURNS)
    image_id = await _add_room_situational_image(db_session, room.room_id)
    return room.room_id, str(image_id), room.turns[_ROOM_TURNS][0].id


async def _send_story(db_client: httpx.AsyncClient, db_session: AsyncSession, _: pytest.MonkeyPatch) -> _Case:
    room_id, cell_id, _last_user = await _story_room(db_client, db_session)
    return _Case("POST", f"/chat-rooms/{room_id}/messages", {"content": "마을을 떠나자"}, cell_id)


async def _edit_story(db_client: httpx.AsyncClient, db_session: AsyncSession, _: pytest.MonkeyPatch) -> _Case:
    room_id, cell_id, last_user = await _story_room(db_client, db_session)
    return _Case("PATCH", f"/chat-rooms/{room_id}/messages/{last_user}", {"content": "고쳐 말하면, 떠나자"}, cell_id)


async def _regenerate_story(db_client: httpx.AsyncClient, db_session: AsyncSession, _: pytest.MonkeyPatch) -> _Case:
    room_id, cell_id, _last_user = await _story_room(db_client, db_session)
    return _Case("POST", f"/chat-rooms/{room_id}/regenerate", None, cell_id)


async def _regenerate_story_shortcut(
    db_client: httpx.AsyncClient, db_session: AsyncSession, _: pytest.MonkeyPatch
) -> _Case:
    """마지막 응답이 단축어로 보낸 턴이다 — 그 턴 기록이 단축어를 가리킨다. 재생성 프롬프트에 단축어 문안이 실려
    `regenerate-story` 와 생성 프롬프트만 다르다."""
    room_id, cell_id, _last_user = await _story_room(db_client, db_session)
    version_id = await db_session.scalar(sa.select(ChatRoom.content_version_id).where(ChatRoom.id == room_id))
    assert version_id is not None
    shortcut = Shortcut(
        entity_id=uuid.uuid4(),
        content_version_id=version_id,
        name="수색",
        description="주변을 수색한다",
        prompt="플레이어가 주변을 자세히 수색하는 상황을 묘사하라",
    )
    db_session.add(shortcut)
    last_reply_id = await db_session.scalar(
        sa.select(ChatMessage.id)
        .where(ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.ASSISTANT)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    assert last_reply_id is not None
    db_session.add(
        _make_chat_turn(
            room_id, assistant_message_id=last_reply_id, turn_number=_ROOM_TURNS, shortcut_entity_id=shortcut.entity_id
        )
    )
    await db_session.commit()
    return _Case("POST", f"/chat-rooms/{room_id}/regenerate", None, cell_id)


async def _send_character(db_client: httpx.AsyncClient, db_session: AsyncSession, _: pytest.MonkeyPatch) -> _Case:
    room_id, image_id, _last_user = await _character_room(db_client, db_session)
    return _Case("POST", f"/chat-rooms/{room_id}/messages", {"content": "골목으로 가자"}, image_id)


async def _edit_character(db_client: httpx.AsyncClient, db_session: AsyncSession, _: pytest.MonkeyPatch) -> _Case:
    room_id, image_id, last_user = await _character_room(db_client, db_session)
    return _Case("PATCH", f"/chat-rooms/{room_id}/messages/{last_user}", {"content": "고쳐 말하면, 골목으로"}, image_id)


async def _regenerate_character(db_client: httpx.AsyncClient, db_session: AsyncSession, _: pytest.MonkeyPatch) -> _Case:
    room_id, image_id, _last_user = await _character_room(db_client, db_session)
    return _Case("POST", f"/chat-rooms/{room_id}/regenerate", None, image_id)


async def _start_preview(
    db_client: httpx.AsyncClient, db_session: AsyncSession, *, story: bool
) -> tuple[str, str | None]:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_asset(db_session, owner_user_id=user.id, status=AssetStatus.READY)
    await db_session.commit()
    await _login_as(db_client, user.id)
    cell_id: str | None = None
    if story:
        cell, payload = _preview_story_payload(asset.id)
        cell_id = str(cell)
    else:
        payload = _preview_character_payload()
    started = await db_client.post("/preview-sessions", json=payload)
    assert started.status_code == 201, started.text
    session_id = started.json()["previewSessionId"]
    assert isinstance(session_id, str)
    return session_id, cell_id


async def _preview_story(db_client: httpx.AsyncClient, db_session: AsyncSession, _: pytest.MonkeyPatch) -> _Case:
    session_id, cell_id = await _start_preview(db_client, db_session, story=True)
    return _Case("POST", f"/preview-sessions/{session_id}/messages", {"content": "행복해지자"}, cell_id)


async def _preview_character(db_client: httpx.AsyncClient, db_session: AsyncSession, _: pytest.MonkeyPatch) -> _Case:
    session_id, _cell = await _start_preview(db_client, db_session, story=False)
    return _Case("POST", f"/preview-sessions/{session_id}/messages", {"content": "안녕"}, None)


async def _send_story_sonnet(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> _Case:
    """미리보기는 모델을 싣지 않아 언제나 Gemini 라, 상위 모델 경우는 실제 방이어야 한다."""
    user = await _make_user_with_clover_lot(db_session, clover_balance=1000)
    await db_session.commit()
    await _allow_chat_premium(db_session, monkeypatch, user.id)
    room = await _open_room(db_client, db_session, turns=_ROOM_TURNS, lane="story", user=user)
    cell_id = await _add_room_cell_and_endings(db_session, room.room_id, _ENDING_GATES)
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(chat_model="sonnet"))
    # 테스트 DB 의 상위 모델 세트 생성 문안은 Gemini 세트와 같아, 그대로면 어느 세트로 조립했는지가 sha 에 드러나지 않는다.
    # 상위 모델 세트의 생성 문안에만 표지를 붙여 "생성은 모델 세트, 판정·요약은 Gemini 세트"가 뒤바뀌면 장부가 바뀌게 한다.
    marked = await db_session.scalars(
        sa.update(PromptSection)
        .where(
            PromptSection.prompt_set_id.in_(sa.select(PromptSet.id).where(PromptSet.model == "sonnet")),
            PromptSection.channel == "generation",
        )
        .values(body=PromptSection.body + " (상위 모델 세트)")
        .returning(PromptSection.id)
    )
    assert marked.all(), "상위 모델 세트에 생성 문안이 없다"
    await db_session.commit()
    keys = await redis_client.keys(f"{ACTIVE_PROMPT_SET_KEY_PREFIX}*")
    if keys:
        await redis_client.delete(*keys)
    return _Case("POST", f"/chat-rooms/{room.room_id}/messages", {"content": "마을을 떠나자"}, str(cell_id))


_CASES: dict[str, _Builder] = {
    "send-story": _send_story,
    "edit-story": _edit_story,
    "regenerate-story": _regenerate_story,
    "regenerate-story-shortcut": _regenerate_story_shortcut,
    "send-character": _send_character,
    "edit-character": _edit_character,
    "regenerate-character": _regenerate_character,
    "preview-story": _preview_story,
    "preview-character": _preview_character,
    "send-story-sonnet": _send_story_sonnet,
}

# 경우마다 장부가 지나야 하는 호출 위치 — 이 경로를 지나지 않으면 그 판정 프롬프트는 아무도 지문을 뜨지 않는다. 접기가
# 요약 LLM 을 부르는 것은 30턴 방의 보내기·수정·재생성이다(재생성도 커밋 뒤 접기를 예약한다).
_STORY_TURN_SITES = {
    "chat_generate",
    "chat_stat_judgment",
    "chat_media_book_image",
    "chat_ending_judgment",
    "chat_memory_summary",
}
_CHARACTER_TURN_SITES = {"chat_generate", "chat_situational_image", "chat_memory_summary"}
_REQUIRED_CALL_SITES: dict[str, set[str]] = {
    "send-story": _STORY_TURN_SITES,
    "edit-story": _STORY_TURN_SITES,
    # 기록 없는 응답의 재생성은 스탯을 다시 판정하지 않는다. 단축어 경우는 마지막 턴의 기록(엔딩 없음)이 있어 다시 판정한다.
    "regenerate-story": {"chat_generate", "chat_media_book_image", "chat_memory_summary"},
    "regenerate-story-shortcut": {"chat_generate", "chat_stat_judgment", "chat_media_book_image", "chat_memory_summary"},
    "send-character": _CHARACTER_TURN_SITES,
    "edit-character": _CHARACTER_TURN_SITES,
    "regenerate-character": {"chat_generate", "chat_situational_image", "chat_memory_summary"},
    "preview-story": {
        "preview_generate",
        "preview_stat_judgment",
        "preview_media_book_image",
        "preview_ending_judgment",
    },
    "preview-character": {"preview_generate"},
    "send-story-sonnet": _STORY_TURN_SITES,
}


def test_required_call_sites_cover_every_chat_and_preview_call_site() -> None:
    """경우들이 함께 덮는 호출 위치가 채팅·미리보기 호출 위치 전부다 — 새 판정 호출 위치가 생기면 여기서 빨개져 경우를
    더하게 한다."""
    chat_sites = {site for site in get_args(LLMCallSite) if site.startswith(("chat_", "preview_"))}
    covered: set[str] = set()
    for sites in _REQUIRED_CALL_SITES.values():
        covered |= sites
    assert covered == chat_sites


def _dump_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        # 판정 프롬프트 줄은 리플레이가 거르는 줄이라 여기 남기지 않는다 — 그 줄은 판정 덤프 테스트가 따로 본다.
        if record["kind"] == "judgment":
            continue
        lines.append(
            {"hasRoomId": record["roomId"] is not None, "turn": record["turn"], "chatModel": record["chatModel"]}
        )
    return lines


def test_recorded_cases_are_exactly_the_parametrized_cases() -> None:
    _assert_recorded_cases(FIXTURE_PATH, _CASES)


@pytest.mark.parametrize("case", list(_CASES))
async def test_llm_requests_of_a_turn_match_the_recorded_ledger(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
) -> None:
    turn = await _CASES[case](db_client, db_session, monkeypatch)
    dump_path = tmp_path / "prompts.jsonl"
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump_path))
    ledger: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    gemini = _LedgerLLM("gemini", ledger, ids, turn.match_id)
    bedrock = _LedgerLLM("bedrock", ledger, ids, turn.match_id)
    _override_llm_client(RoutingLLMClient(gemini, factories={"bedrock": lambda: bedrock}))
    try:
        response = await db_client.request(turn.method, turn.path, json=turn.body)
    finally:
        _clear_llm_override()

    assert response.status_code == 200, response.text
    assert [event["type"] for event in _parse_sse_events(response.text)][-1] == "done"
    assert {entry["callSite"] for entry in ledger} == _REQUIRED_CALL_SITES[case]
    _assert_characterization(FIXTURE_PATH, case, {"calls": ledger, "promptDump": _dump_lines(dump_path)})
