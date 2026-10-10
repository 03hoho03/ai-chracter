"""채팅 턴의 실패 경로를 칸마다 지금 동작 그대로 고정한다 — 버그로 보이는 동작도 고치지 않고 기록한다.

칸은 (실패 종류, 경로)다. 경로는 보내기·수정·재생성(스토리 방, 그림 판정 실패와 재생성의 커밋 뒤 상황 이미지 URL
서명 실패만 캐릭터 방)과 미리보기 스토리·캐릭터다.
칸마다 남기는 것:

- HTTP 상태와 SSE 이벤트 순서(토큰 글, 오류·정책 문구, 스탯 변화, 엔딩, 마지막 메시지의 글·그림 유무)
- 앱 밖으로 샌 예외(있으면 — 그때 스트림은 done·error 없이 끊긴다)
- 저장된 상태: 실제 방은 컬럼 `select()` 로 읽은 턴 수·엔딩 여부·메시지·스탯·폐기 기록, 미리보기는 Redis 세션
- 클로버 잔액 증감과 원장 종류(환급 여부)
- 그 턴에 나간 LLM 호출(메서드, 호출 위치)
- Bugsink 로 올린 실패(예외 타입, `dependency` 태그) — `sentry_sdk.capture_exception` 자체를 바꿔 끼워 잡으므로 올리는
  코드가 어느 모듈로 옮겨 가도 빗나가지 않는다
- background 로 예약된 일(요약 접기)

실패는 될 수 있으면 데이터·경계에서 만든다: 프롬프트 렌더 실패는 활성 세트의 그 채널 문안에 없는 자리표시자를 넣어서, DB
읽기 실패는 그 문장 대신 `SELECT 1/0` 을 요청 세션에서 실제로 보내 트랜잭션을 진짜 aborted 로 만들어서, 쓰기 실패는 쓰기
구간 커밋에 외래 키 위반 행을 얹어서, 끊김은 앱을 직접 불러 `http.disconnect` 를 보내서 만든다. 끊김은 클라이언트가 그
앞에 나간 이벤트를 실제로 받은 뒤에 보낸다 — 운영에서 끊김은 마지막 송신보다 한참 뒤에 오므로, 같은 틱의 끊김이 송신 중인
이벤트를 지우는 하네스 산물을 기록하지 않게.

요청 세션의 커밋이 진짜 경계가 되도록 `committing_request_session` 위에서 돈다. 그 하네스는 요청 세션과 환급 세션이 커넥션
하나를 SAVEPOINT 로 나눠 써서, 요청 세션의 트랜잭션이 열린 채 환급하면 환급이 그 SAVEPOINT 안에 들어가 요청 세션이 닫힐 때
함께 되돌려진다. 운영의 환급은 다른 커넥션의 독립 트랜잭션이라 요청 세션과 무관하게 남고 커밋된 상태만 본다 — 그래서
요청 세션 트랜잭션이 열린 동안 불린 환급은 그 세션이 닫힌 뒤에 돌린다(`_refunds_outlive_the_request_session`).

실패를 만드는 장치가 실제로 그 자리에 닿았는지는 칸마다 따로 확인한다 — 닿지 않은 채 성공한 턴이 기대값으로 굳지 않게.

기대값은 지금 동작을 기록한 것이다(`fixtures/chat_turn_failure_matrix.json`). 다시 뜨는 법은
`factories._assert_characterization`.

같은 파일에 실패가 아닌 두 성질도 둔다 — 요약 접기 같은 background 일이 도는 순간 요청 세션 트랜잭션이 닫혀 있는지,
미리보기의 스탯 판정과 칸 판정이 동시에 도는지.
"""

import asyncio
import inspect
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sentry_sdk
import sqlalchemy as sa
from fastapi import BackgroundTasks
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.types import Message

from api.chat.preview_session import get_preview_session
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MemorySummaryResult,
    StatRuleJudgmentResult,
)
from api.chat.prompt_set_cache import ACTIVE_PROMPT_SET_KEY_PREFIX
from api.core import clover, rate_limit_gate
from api.core import s3 as s3_module
from api.core.redis import redis_client
from api.db.models import (
    AssetStatus,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomStat,
    Ending,
    PromptSection,
    StartingSetup,
    StatRule,
    User,
)
from api.db.models.chat import DiscardedResponse
from api.db.models.clover import CloverLedger
from api.db.session import get_db_session
from api.llm.client import (
    LLMCallContext,
    LLMClient,
    LLMClientError,
    LLMPolicyViolationError,
    LLMRateLimitError,
)
from api.llm.gemini import GeminiLLMClient
from api.main import app
from factories import (
    _add_room_cell_and_endings,
    _add_room_situational_image,
    _assert_characterization,
    _assert_recorded_cases,
    _call_until_disconnect,
    _clear_llm_override,
    _login_as,
    _make_asset,
    _make_user,
    _make_user_with_clover_lot,
    _open_room,
    _open_transaction_probe,
    _override_llm_client,
    _parse_sse_events,
    _preview_character_payload,
    _preview_story_payload,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chat_turn_failure_matrix.json"

_START_BALANCE = 100
# 보내기는 2턴째(게이트 2 의 차례), 수정은 하나뿐인 사용자 메시지를 고쳐 1턴째(게이트 1 의 차례)다.
_ENDING_GATES = (1, 2)
# 끊김을 기다리며 멈추는 시간. 끊김이 닿으면 그 자리에서 취소된다 — 닿지 않으면 앱 호출의 상한(10초)이 먼저 끊는다.
_HANG_SECONDS = 30


# ── 가짜 LLM ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _Script:
    """칸이 바꾸는 LLM 동작. 기본은 모든 판정이 무언가를 하는 성공 턴이다(스탯 규칙 a1 발동, 그림 일치, 엔딩 발동)."""

    tokens: list[str] = field(default_factory=lambda: ["오늘은 ", "비가 와."])
    # 토큰을 다 낸 뒤 올릴 생성 예외.
    generation_error: Exception | None = None
    # 토큰을 다 낸 뒤 끊김을 알리고 멈춘다.
    hang_after_tokens: bool = False
    # 토큰을 다 낸 뒤 부를 일(생성 도중 방 삭제 등).
    after_tokens: Callable[[], Awaitable[None]] | None = None
    # 생성을 이 클라이언트에 맡긴다(진짜 공급자 클라이언트의 예외 정규화를 지나게 할 때).
    generation_delegate: LLMClient | None = None
    # 응답 스키마 → 그 판정에서 올릴 예외.
    judgment_errors: dict[type, Exception] = field(default_factory=dict)
    # 첫 판정 호출에서 끊김을 알리고 멈춘다.
    hang_on_first_judgment: bool = False
    # 스탯 판정과 칸 판정이 서로를 기다린다 — 둘이 동시에 떠 있을 때만 둘 다 끝나고, 차례로 불리면 먼저 불린 쪽이 시간
    # 초과로 실패한다.
    rendezvous: bool = False


class _MatrixLLM(LLMClient):
    def __init__(self, script: _Script, *, match_id: str | None, disconnect: asyncio.Event) -> None:
        self._script = script
        self._match_id = match_id
        self._disconnect = disconnect
        self._hung = False
        self._arrived = {StatRuleJudgmentResult: asyncio.Event(), ImageMatchJudgmentResult: asyncio.Event()}
        self.calls: list[list[str]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append(["generate", usage.call_site])
        script = self._script
        if script.generation_delegate is not None:
            async for token in script.generation_delegate.generate(
                prompt, system_instruction, stop_sequences, usage=usage
            ):
                yield token
            return
        for token in script.tokens:
            yield token
        if script.after_tokens is not None:
            await script.after_tokens()
        if script.hang_after_tokens:
            self._disconnect.set()
            await asyncio.sleep(_HANG_SECONDS)
        if script.generation_error is not None:
            raise script.generation_error

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.calls.append(["generate_structured", usage.call_site])
        script = self._script
        if response_schema is MemorySummaryResult:
            return MemorySummaryResult(summary="요약")
        if script.hang_on_first_judgment and not self._hung:
            self._hung = True
            self._disconnect.set()
            await asyncio.sleep(_HANG_SECONDS)
        if script.rendezvous and response_schema in self._arrived:
            self._arrived[response_schema].set()
            other = ImageMatchJudgmentResult if response_schema is StatRuleJudgmentResult else StatRuleJudgmentResult
            try:
                await asyncio.wait_for(self._arrived[other].wait(), timeout=2)
            except TimeoutError as exc:
                raise LLMClientError("다른 판정이 동시에 불리지 않았다") from exc
        error = script.judgment_errors.get(response_schema)
        if error is not None:
            raise error
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=["a1"])
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=True)
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=self._match_id)
        raise AssertionError(f"예상하지 못한 응답 스키마: {response_schema}")


# ── 경로 ─────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Target:
    method: str
    path: str
    body: dict[str, object] | None
    user_id: uuid.UUID
    # 그림 판정이 고를 후보(칸·상황 이미지) id.
    match_id: str | None
    room_id: uuid.UUID | None = None
    preview_session_id: str | None = None


async def _paid_user(db_session: AsyncSession) -> User:
    """클로버로 낼 수밖에 없는 사용자 — 오늘 확인을 마친 잔액 100. 상한은 셋업 뒤에 0 으로 낮춘다(테스트 본문)."""
    user = await _make_user_with_clover_lot(
        db_session, clover_balance=_START_BALANCE, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    await db_session.commit()
    return user


def _room_request(
    action: str, room_id: uuid.UUID, user_message_id: uuid.UUID
) -> tuple[str, str, dict[str, object] | None]:
    if action == "send":
        return "POST", f"/chat-rooms/{room_id}/messages", {"content": "마을을 떠나자"}
    if action == "edit":
        return "PATCH", f"/chat-rooms/{room_id}/messages/{user_message_id}", {"content": "고쳐 말하면, 마을을 떠나자"}
    return "POST", f"/chat-rooms/{room_id}/regenerate", None


async def _story_target(db_client: httpx.AsyncClient, db_session: AsyncSession, action: str) -> _Target:
    user = await _paid_user(db_session)
    room = await _open_room(db_client, db_session, turns=1, lane="story", user=user)
    cell_id = await _add_room_cell_and_endings(db_session, room.room_id, _ENDING_GATES)
    method, path, body = _room_request(action, room.room_id, room.turns[1][0].id)
    return _Target(method, path, body, user.id, str(cell_id), room_id=room.room_id)


async def _character_target(db_client: httpx.AsyncClient, db_session: AsyncSession, action: str) -> _Target:
    user = await _paid_user(db_session)
    room = await _open_room(db_client, db_session, turns=1, user=user)
    image_id = await _add_room_situational_image(db_session, room.room_id)
    method, path, body = _room_request(action, room.room_id, room.turns[1][0].id)
    return _Target(method, path, body, user.id, str(image_id), room_id=room.room_id)


async def _preview_target(db_client: httpx.AsyncClient, db_session: AsyncSession, *, story: bool) -> _Target:
    user = await _paid_user(db_session)
    asset = await _make_asset(db_session, owner_user_id=user.id, status=AssetStatus.READY)
    await db_session.commit()
    await _login_as(db_client, user.id)
    match_id: str | None = None
    if story:
        cell_id, payload = _preview_story_payload(asset.id)
        match_id = str(cell_id)
    else:
        payload = _preview_character_payload()
    started = await db_client.post("/preview-sessions", json=payload)
    assert started.status_code == 201, started.text
    session_id = started.json()["previewSessionId"]
    assert isinstance(session_id, str)
    return _Target(
        "POST",
        f"/preview-sessions/{session_id}/messages",
        {"content": "행복해지자"},
        user.id,
        match_id,
        preview_session_id=session_id,
    )


_SURFACES: dict[str, Callable[[httpx.AsyncClient, AsyncSession], Awaitable[_Target]]] = {
    "send": lambda client, session: _story_target(client, session, "send"),
    "edit": lambda client, session: _story_target(client, session, "edit"),
    "regenerate": lambda client, session: _story_target(client, session, "regenerate"),
    "send-character": lambda client, session: _character_target(client, session, "send"),
    "edit-character": lambda client, session: _character_target(client, session, "edit"),
    "regenerate-character": lambda client, session: _character_target(client, session, "regenerate"),
    "preview-story": lambda client, session: _preview_target(client, session, story=True),
    "preview-character": lambda client, session: _preview_target(client, session, story=False),
}


# ── 실패 만들기 ─────────────────────────────────────────────────────────────────────────


class _Outbox(list[Message]):
    """앱이 클라이언트로 보낸 ASGI 메시지. 하나 쌓일 때마다 `grew` 를 세워 받은 것을 기다리는 쪽을 깨운다."""

    def __init__(self) -> None:
        super().__init__()
        self.grew = asyncio.Event()

    def append(self, message: Message) -> None:
        super().append(message)
        self.grew.set()


@dataclass
class _Ctx:
    db_client: httpx.AsyncClient
    db_session: AsyncSession
    monkeypatch: pytest.MonkeyPatch
    target: _Target
    script: _Script
    disconnect: asyncio.Event
    sentry: list[list[str | None]]
    # 앱이 클라이언트로 보낸 ASGI 메시지 — 요청 도중에도 "클라이언트가 무엇을 받았는가"를 읽는다.
    sent: _Outbox = field(default_factory=_Outbox)
    # (설명, 실패 장치가 그 자리에 닿았는가) — 요청 뒤에 전부 참이어야 한다.
    witnesses: list[tuple[str, Callable[[], bool]]] = field(default_factory=list)
    # 요청 뒤에 걷어낼 이벤트 리스너.
    cleanups: list[Callable[[], None]] = field(default_factory=list)


_Arm = Callable[[_Ctx], Awaitable[None]]


def _captured(ctx: _Ctx, exception_type: str, dependency: str) -> Callable[[], bool]:
    return lambda: [exception_type, dependency] in ctx.sentry


def _break_channel(channel: str) -> _Arm:
    """활성 세트의 `channel` 문안(늘 렌더되는 섹션)에 값이 없는 자리표시자를 붙여 렌더가 `PromptRenderError` 로 끝나게
    한다. 셋업이 캐시에 남긴 세트를 지워 요청이 고친 문안을 읽게 한다."""

    async def arm(ctx: _Ctx) -> None:
        await ctx.db_session.execute(
            sa.update(PromptSection)
            .where(PromptSection.channel == channel, PromptSection.conditional.is_(False))
            .values(body=PromptSection.body + " {failure_matrix_missing_value}")
        )
        await ctx.db_session.commit()
        keys = await redis_client.keys(f"{ACTIVE_PROMPT_SET_KEY_PREFIX}*")
        if keys:
            await redis_client.delete(*keys)
        ctx.witnesses.append(
            (f"{channel} 렌더 실패가 올라가지 않았다", _captured(ctx, "PromptRenderError", "prompt_render"))
        )

    return arm


def _script_change(change: Callable[[_Script], None]) -> _Arm:
    async def arm(ctx: _Ctx) -> None:
        change(ctx.script)

    return arm


def _set_generation_error(error: Exception, *, tokens: list[str] | None = None) -> Callable[[_Script], None]:
    def change(script: _Script) -> None:
        script.generation_error = error
        if tokens is not None:
            script.tokens = tokens

    return change


def _set_judgment_error(schema: type) -> Callable[[_Script], None]:
    def change(script: _Script) -> None:
        script.judgment_errors[schema] = LLMClientError("판정 실패")

    return change


async def _generation_timeout(ctx: _Ctx) -> None:
    """진짜 Gemini 클라이언트에 SDK 경계만 가짜로 두고, 스트림 요청이 읽기 시간 초과로 끝나게 한다."""

    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        raise httpx.ReadTimeout("시간 초과")

    gemini = GeminiLLMClient(api_key="test-key")
    ctx.monkeypatch.setattr(
        gemini,
        "_client",
        SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate_content_stream))),
    )
    ctx.script.generation_delegate = gemini


async def _hang_during_generation(ctx: _Ctx) -> None:
    ctx.script.hang_after_tokens = True
    ctx.witnesses.append(("생성 도중 끊김을 알리지 않았다", ctx.disconnect.is_set))


async def _hang_during_judgment(ctx: _Ctx) -> None:
    ctx.script.hang_on_first_judgment = True
    ctx.witnesses.append(("판정 도중 끊김을 알리지 않았다", ctx.disconnect.is_set))


async def _delete_room_during_generation(ctx: _Ctx) -> None:
    statuses: list[int] = []

    async def delete_room() -> None:
        statuses.append((await ctx.db_client.delete(f"/chat-rooms/{ctx.target.room_id}")).status_code)

    ctx.script.after_tokens = delete_room
    ctx.witnesses.append(("생성 도중 방 삭제가 성공하지 않았다", lambda: statuses == [204]))


async def _abort_stat_rule_read(ctx: _Ctx) -> None:
    """스탯 규칙을 읽는 첫 문장 대신 요청 세션에서 `SELECT 1/0` 을 보내 트랜잭션을 진짜 aborted 로 만든다.

    환급은 따로 손대지 않는다 — aborted 트랜잭션이 열린 채 불린 환급은 모든 칸에 걸린
    `_refunds_outlive_the_request_session` 이 요청 세션이 닫힌(SAVEPOINT 로 되감긴) 뒤에 돌리므로, aborted 트랜잭션 위에서
    환급 세션이 시작해 실패하는 하네스 산물이 생기지 않는다."""
    aborted: list[AsyncSession] = []
    original_execute = AsyncSession.execute

    async def execute(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if (
            not aborted
            and isinstance(statement, sa.Select)
            and statement.column_descriptions
            and statement.column_descriptions[0].get("entity") is StatRule
        ):
            aborted.append(self)
            return await original_execute(self, sa.text("SELECT 1/0"))
        return await original_execute(self, statement, *args, **kwargs)

    ctx.monkeypatch.setattr(AsyncSession, "execute", execute)
    ctx.witnesses.append(("스탯 규칙 읽기에 닿지 않았다", lambda: bool(aborted)))


_ASSISTANT_WRITE = "failure_matrix_assistant_write"


def _flags_assistant_writes(ctx: _Ctx) -> None:
    """세션이 새 AI 응답 행을 flush 하면 그 세션에 표시를 남긴다 — 쓰기 구간 커밋을 다른 커밋과 가른다."""

    def before_flush(session: Session, _context: Any, _instances: Any) -> None:
        if any(isinstance(obj, ChatMessage) and obj.role == ChatMessageRole.ASSISTANT for obj in session.new):
            session.info[_ASSISTANT_WRITE] = True

    sa.event.listen(Session, "before_flush", before_flush)
    ctx.cleanups.append(lambda: sa.event.remove(Session, "before_flush", before_flush))


async def _fail_write_commit(ctx: _Ctx) -> None:
    """쓰기 구간 커밋(새 AI 응답을 담은 루트 트랜잭션의 커밋)에 없는 방을 가리키는 스탯 행을 얹어 외래 키 위반으로
    끝나게 한다. SAVEPOINT 의 커밋(노출 기록)은 건드리지 않는다."""
    _flags_assistant_writes(ctx)
    fired: list[bool] = []

    def before_commit(session: Session) -> None:
        if fired or session.in_nested_transaction():
            return
        pending_reply = any(
            isinstance(obj, ChatMessage) and obj.role == ChatMessageRole.ASSISTANT for obj in session.new
        )
        if session.info.get(_ASSISTANT_WRITE) or pending_reply:
            fired.append(True)
            session.add(ChatRoomStat(chat_room_id=uuid.uuid4(), stat_entity_id=uuid.uuid4(), current_value=Decimal(0)))

    sa.event.listen(Session, "before_commit", before_commit)
    ctx.cleanups.append(lambda: sa.event.remove(Session, "before_commit", before_commit))
    ctx.witnesses.append(("쓰기 구간 커밋에 닿지 않았다", lambda: bool(fired)))


async def _cancel_after_write_commit(ctx: _Ctx) -> None:
    """쓰기 구간 커밋이 실제로 끝난 직후 끊김을 알리고 멈춘다 — 취소가 그 자리(커밋 `await` 직후)에 닿는다."""
    _flags_assistant_writes(ctx)
    original_commit = AsyncSession.commit
    fired: list[bool] = []

    async def commit(self: AsyncSession) -> None:
        await original_commit(self)
        if not fired and self.info.pop(_ASSISTANT_WRITE, False):
            fired.append(True)
            ctx.disconnect.set()
            await asyncio.sleep(_HANG_SECONDS)

    ctx.monkeypatch.setattr(AsyncSession, "commit", commit)
    ctx.witnesses.append(("쓰기 구간 커밋 뒤에 끊지 않았다", lambda: bool(fired)))


def _client_received(ctx: _Ctx, kind: str) -> bool:
    body = b"".join(message.get("body", b"") for message in ctx.sent if message["type"] == "http.response.body")
    return any(event["type"] == kind for event in _parse_sse_events(body.decode("utf-8")))


# 저장이 `done` 을 기다리는 상한. `done` 이 저장 뒤로 밀린 코드에서는 이만큼 기다린 뒤 그대로 끊어, 기록에서 `done` 이 빠진다.
_DONE_WAIT_SECONDS = 2


def _preview_save(behavior: str) -> _Arm:
    """미리보기 세션 저장(Redis SET)을 바꾼다 — `hang` 은 클라이언트가 `done` 을 실제로 받을 때까지 저장을 붙잡아 둔 뒤
    끊김을 알리고 멈추고, `fail` 은 Redis 오류로 끝난다. 미리보기 세션 키에만 걸고, 저장 함수가 아니라 그 클라이언트의
    SET 을 바꿔 저장 호출이 어디로 옮겨 가도 빗나가지 않게 한다.

    `hang` 이 `done` 수신을 기다리는 이유: 끊김을 저장과 같은 틱에 보내면 송신 쪽이 `done` 을 내보내기 전에 응답이 취소돼,
    `done` 을 저장 앞에서 낸 지금 코드와 저장을 `done` 앞으로 옮긴 코드가 같은 기록(`done` 없음)을 낸다. 받은 뒤에 끊으면
    지금 코드는 `done` 을 남기고, 저장이 `done` 앞으로 옮겨 가면 `done` 이 오지 않아 상한 뒤 끊긴 기록이 달라진다."""

    async def arm(ctx: _Ctx) -> None:
        original_set = redis_client.set
        reached: list[bool] = []

        async def set_(name: Any, value: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(name, str) and name.startswith("preview-session:"):
                reached.append(True)
                if behavior == "fail":
                    raise RedisError("미리보기 세션 저장 실패")
                try:
                    async with asyncio.timeout(_DONE_WAIT_SECONDS):
                        while not _client_received(ctx, "done"):
                            ctx.sent.grew.clear()
                            await ctx.sent.grew.wait()
                except TimeoutError:
                    pass
                ctx.disconnect.set()
                await asyncio.sleep(_HANG_SECONDS)
            return await original_set(name, value, *args, **kwargs)

        ctx.monkeypatch.setattr(redis_client, "set", set_)
        ctx.witnesses.append(("미리보기 세션 저장에 닿지 않았다", lambda: bool(reached)))

    return arm


async def _fail_post_commit_signing(ctx: _Ctx) -> None:
    """커밋 뒤 그림 서명을 실패시킨다. 서명 함수가 쓰는 URL 조립을 바꿔, 서명을 부르는 자리가 옮겨 가도 빗나가지 않게 한다."""
    reached: list[bool] = []

    def boom(*_args: Any, **_kwargs: Any) -> str:
        reached.append(True)
        raise RuntimeError("서명 실패")

    ctx.monkeypatch.setattr(s3_module, "build_windowed_presigned_get_url", boom)
    ctx.witnesses.append(("그림 서명에 닿지 않았다", lambda: bool(reached)))


async def _fail_epilogue_display(ctx: _Ctx) -> None:
    """도달할 엔딩의 에필로그에 방 버전의 칸 태그를 넣고 커밋 뒤 그림 서명을 실패시킨다 — 에필로그를 화면용으로 해석하는
    자리가 서명에서 실패한다. 판정 칸 서명도 같은 장치로 함께 실패한다."""
    assert ctx.target.room_id is not None
    version_id = sa.select(ChatRoom.content_version_id).where(ChatRoom.id == ctx.target.room_id).scalar_subquery()
    setup_ids = sa.select(StartingSetup.id).where(StartingSetup.content_version_id == version_id)
    await ctx.db_session.execute(
        sa.update(Ending)
        .where(Ending.starting_setup_id.in_(setup_ids))
        .values(epilogue=Ending.epilogue + "\n\n{{img::민아/교실}}")
    )
    await ctx.db_session.commit()
    await _fail_post_commit_signing(ctx)
    ctx.witnesses.append(("에필로그 그림 해석이 서명 실패를 흡수하지 않았다", _captured(ctx, "RuntimeError", "db")))


_ROOM = ("send", "edit", "regenerate")
_ALL = (*_ROOM, "preview-story", "preview-character")
_STORY_ALL = (*_ROOM, "preview-story")

_CELLS: dict[str, tuple[tuple[str, ...], _Arm]] = {
    "generation-prompt-render-failure": (_ALL, _break_channel("generation")),
    "generation-error-before-first-token": (
        _ALL,
        _script_change(_set_generation_error(LLMClientError("생성 실패"), tokens=[])),
    ),
    "generation-error-after-tokens": (_STORY_ALL, _script_change(_set_generation_error(LLMClientError("생성 실패")))),
    "generation-rate-limit": (
        _STORY_ALL,
        _script_change(_set_generation_error(LLMRateLimitError("쿼터 소진"), tokens=[])),
    ),
    "generation-policy-violation-after-tokens": (
        _ALL,
        _script_change(_set_generation_error(LLMPolicyViolationError("안전 차단"))),
    ),
    "generation-timeout": (("send",), _generation_timeout),
    "empty-generation": (_STORY_ALL, _script_change(lambda script: setattr(script, "tokens", []))),
    "disconnect-during-generation": (_STORY_ALL, _hang_during_generation),
    "stat-judgment-error": (
        ("send", "edit", "preview-story"),
        _script_change(_set_judgment_error(StatRuleJudgmentResult)),
    ),
    "ending-judgment-error": (
        ("send", "edit", "preview-story"),
        _script_change(_set_judgment_error(EndingJudgmentResult)),
    ),
    "ending-judgment-prompt-render-failure": (("send", "preview-story"), _break_channel("ending_judgment")),
    "media-judgment-error": (_STORY_ALL, _script_change(_set_judgment_error(ImageMatchJudgmentResult))),
    "media-judgment-prompt-render-failure": (("send", "regenerate", "preview-story"), _break_channel("image_judgment")),
    "situational-image-judgment-error": (
        ("send-character", "edit-character", "regenerate-character"),
        _script_change(_set_judgment_error(ImageMatchJudgmentResult)),
    ),
    "stat-rule-read-aborts-the-transaction": (("send", "edit"), _abort_stat_rule_read),
    "stat-judgment-prompt-render-failure": (("send", "edit", "preview-story"), _break_channel("stat_rule_judgment")),
    "write-commit-fails": (_ROOM, _fail_write_commit),
    "room-deleted-before-the-write": (("send", "regenerate"), _delete_room_during_generation),
    "cancel-after-the-write-commit": (_ROOM, _cancel_after_write_commit),
    "disconnect-during-judgment": (_STORY_ALL, _hang_during_judgment),
    "cancel-after-done-before-the-preview-save": (("preview-story",), _preview_save("hang")),
    "preview-save-fails": (("preview-story",), _preview_save("fail")),
    "post-commit-signing-failure": (("send", "regenerate", "regenerate-character"), _fail_post_commit_signing),
    "epilogue-display-failure": (("send",), _fail_epilogue_display),
}


# ── 기록 ─────────────────────────────────────────────────────────────────────────────────

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _norm(value: object, ids: dict[str, str]) -> str | None:
    """id 를 처음 나온 순서의 번호로 바꾼다(그림 후보는 `<candidate>`)."""
    if value is None:
        return None
    return _UUID.sub(lambda m: ids.setdefault(m.group(0), f"<id{len(ids) + 1}>"), str(value))


def _event(event: dict[str, Any], ids: dict[str, str]) -> dict[str, Any]:
    kind = event["type"]
    if kind == "token":
        return {"type": kind, "delta": event["delta"]}
    if kind in ("error", "policyWarning"):
        return {"type": kind, "message": event["message"]}
    if kind == "statChange":
        return {"type": kind, "statId": _norm(event["statId"], ids), "newValue": event["newValue"]}
    if kind == "endingReached":
        return {
            "type": kind,
            "endingId": _norm(event["endingId"], ids),
            "epilogue": event.get("epilogue"),
            "mediaTagImages": sorted(str(_norm(key, ids)) for key in event.get("mediaTagImages") or {}),
        }
    if kind == "done":
        final = event["finalMessage"]
        return {
            "type": kind,
            "content": final["content"],
            "imageId": _norm(final.get("imageId"), ids),
            "hasImageUrl": bool(final.get("imageUrl")),
        }
    return {"type": kind}


_TERMINAL_EVENTS = frozenset({"done", "error", "policyWarning"})


def _tokens_of_a_cut_stream(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """끝 이벤트(`done`·`error`·`policyWarning`) 없이 끊긴 스트림에서는 이어진 토큰들을 `{"type": "tokens"}` 하나로 접는다.
    그런 스트림에서 클라이언트에 닿은 토큰 개수는 마지막 송신과 끊김 사이에 `await` 가 몇 개 끼었느냐에 달려 있어, 동작이
    같은 리팩터에서도 바뀐다. 토큰이 하나도 안 닿은 것과 닿은 것은 접은 뒤에도 갈린다."""
    if any(event["type"] in _TERMINAL_EVENTS for event in events):
        return events
    folded: list[dict[str, Any]] = []
    for event in events:
        if event["type"] != "token":
            folded.append(event)
        elif not folded or folded[-1] != {"type": "tokens"}:
            folded.append({"type": "tokens"})
    return folded


def _exception_names(exc: BaseException) -> list[str]:
    if isinstance(exc, BaseExceptionGroup):
        return sorted({name for inner in exc.exceptions for name in _exception_names(inner)})
    return [type(exc).__name__]


async def _drive(ctx: _Ctx) -> dict[str, Any]:
    """앱을 직접 불러 상태 줄과 SSE 이벤트, 앱 밖으로 샌 예외를 모은다. httpx 는 앱 예외가 나면 그 앞에 나간 이벤트를
    돌려주지 않아 직접 부른다."""
    sent = ctx.sent
    escaped: list[str] = []
    target = ctx.target
    try:
        await _call_until_disconnect(ctx.db_client, target.method, target.path, target.body, ctx.disconnect, sent)
    except BaseException as exc:  # 무엇이 올라오든 기록만 한다 — 그 자체가 칸의 결과다
        escaped = _exception_names(exc)
    status = next((message["status"] for message in sent if message["type"] == "http.response.start"), None)
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return {"status": status, "events": _parse_sse_events(body.decode("utf-8")), "escaped": escaped}


async def _room_state(db_session: AsyncSession, room_id: uuid.UUID, ids: dict[str, str]) -> dict[str, Any]:
    room = (
        await db_session.execute(sa.select(ChatRoom.turn_count, ChatRoom.ending_reached).where(ChatRoom.id == room_id))
    ).one_or_none()
    messages = (
        await db_session.execute(
            sa.select(ChatMessage.role, ChatMessage.content, ChatMessage.image_id)
            .where(ChatMessage.chat_room_id == room_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    ).all()
    stats = (
        await db_session.scalars(
            sa.select(ChatRoomStat.current_value)
            .where(ChatRoomStat.chat_room_id == room_id)
            .order_by(ChatRoomStat.stat_entity_id)
        )
    ).all()
    discarded = (
        await db_session.scalars(sa.select(DiscardedResponse.kind).where(DiscardedResponse.chat_room_id == room_id))
    ).all()
    return {
        "room": None if room is None else {"turnCount": room.turn_count, "endingReached": room.ending_reached},
        "messages": [[m.role.value, m.content, _norm(m.image_id, ids)] for m in messages],
        "stats": [str(value) for value in stats],
        "discarded": sorted(discarded),
    }


async def _preview_state(session_id: str, ids: dict[str, str]) -> dict[str, Any]:
    state = await get_preview_session(session_id)
    assert state is not None
    return {
        "turnCount": state.turn_count,
        "endingReached": state.ending_reached,
        "stats": sorted(state.stats.values()),
        "messages": [[m.role.value, m.content, _norm(m.image_id, ids)] for m in state.messages],
    }


async def _clover(db_session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    balance = await db_session.scalar(sa.select(User.clover_balance).where(User.id == user_id))
    assert balance is not None
    kinds = (await db_session.scalars(sa.select(CloverLedger.kind).where(CloverLedger.user_id == user_id))).all()
    return {"balanceDelta": balance - _START_BALANCE, "ledger": sorted(kinds)}


def _record_scheduled(monkeypatch: pytest.MonkeyPatch, scheduled: list[str]) -> None:
    original_add_task = BackgroundTasks.add_task

    def add_task(self: BackgroundTasks, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        scheduled.append(func.__name__)
        original_add_task(self, func, *args, **kwargs)

    monkeypatch.setattr(BackgroundTasks, "add_task", add_task)


def _record_sentry(monkeypatch: pytest.MonkeyPatch, sentry: list[list[str | None]]) -> None:
    def capture_exception(error: BaseException | None = None, **kwargs: Any) -> None:
        tags = kwargs.get("tags") or {}
        sentry.append([type(error).__name__ if error is not None else None, tags.get("dependency")])

    monkeypatch.setattr(sentry_sdk, "capture_exception", capture_exception)


def _refunds_outlive_the_request_session(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """요청 세션의 트랜잭션이 열린 동안 불린 환급을 그 요청 세션이 닫힌 뒤에 돌린다.

    `committing_request_session` 에서 요청 세션과 환급 세션은 한 커넥션의 SAVEPOINT 다. 요청 세션이 SAVEPOINT 를 연 채
    환급하면 환급의 SAVEPOINT 가 그 안에 들어가고, 요청 세션이 커밋 없이 닫히며 바깥 SAVEPOINT 로 되감을 때 환급도 사라진다.
    운영의 환급은 다른 커넥션에서 커밋돼 요청 세션이 어떻게 끝나든 남고, 요청 세션이 커밋하지 않은 쓰기는 보지 않는다.
    요청 세션이 닫힌 뒤(되감기든 커밋이든 끝난 뒤) 같은 인자로 환급하면 그 둘이 그대로 성립한다. 열린 트랜잭션이 없을 때
    불린 환급은 그 자리에서 돈다 — 환급이 바깥 SAVEPOINT 에 들어가 요청과 무관하게 남는 것이 이미 운영과 같다.

    환급 함수 자리를 바꿔 끼우므로, 환급을 부르지 않는 코드는 미뤄 둘 것도 없어 그대로 "환급 없음"으로 기록된다."""
    connection = db_session.bind
    open_sessions: list[AsyncSession] = []
    deferred: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    original_refund = clover.refund_spend_in_new_transaction

    async def request_session() -> AsyncIterator[AsyncSession]:
        try:
            async with AsyncSession(
                bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
            ) as session:
                open_sessions.append(session)
                try:
                    yield session
                finally:
                    open_sessions.remove(session)
        finally:
            if not any(session.in_transaction() for session in open_sessions):
                while deferred:
                    args, kwargs = deferred.pop(0)
                    await original_refund(*args, **kwargs)

    async def refund(*args: Any, **kwargs: Any) -> None:
        if any(session.in_transaction() for session in open_sessions):
            deferred.append((args, kwargs))
            return
        await original_refund(*args, **kwargs)

    # `committing_request_session` 이 건 요청 세션을 같은 모양으로 갈아 끼운다 — `db_client` 가 끝나며 키를 지운다.
    app.dependency_overrides[get_db_session] = request_session
    monkeypatch.setattr(clover, "refund_spend_in_new_transaction", refund)


_PARAMS = [
    pytest.param(cell, surface, id=f"{cell}/{surface}")
    for cell, (surfaces, _) in _CELLS.items()
    for surface in surfaces
]


def test_recorded_cells_are_exactly_the_parametrized_cells() -> None:
    _assert_recorded_cases(
        FIXTURE_PATH, [f"{cell}/{surface}" for cell, (surfaces, _) in _CELLS.items() for surface in surfaces]
    )


@pytest.mark.usefixtures("committing_request_session")
@pytest.mark.parametrize(("cell", "surface"), _PARAMS)
async def test_failure_cell_matches_the_recorded_behavior(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    cell: str,
    surface: str,
) -> None:
    target = await _SURFACES[surface](db_client, db_session)
    # 셋업이 끝난 뒤 상한을 낮춘다 — 이 턴은 클로버로 낸다.
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    _refunds_outlive_the_request_session(monkeypatch, db_session)
    sentry: list[list[str | None]] = []
    ctx = _Ctx(db_client, db_session, monkeypatch, target, _Script(), asyncio.Event(), sentry)
    _surfaces, arm = _CELLS[cell]
    await arm(ctx)
    scheduled: list[str] = []
    _record_scheduled(monkeypatch, scheduled)
    _record_sentry(monkeypatch, sentry)
    fake = _MatrixLLM(ctx.script, match_id=target.match_id, disconnect=ctx.disconnect)

    _override_llm_client(fake)
    try:
        outcome = await _drive(ctx)
    finally:
        _clear_llm_override()
        for cleanup in ctx.cleanups:
            cleanup()

    for description, reached in ctx.witnesses:
        assert reached(), description
    ids: dict[str, str] = {target.match_id: "<candidate>"} if target.match_id is not None else {}
    if target.room_id is not None:
        state = await _room_state(db_session, target.room_id, ids)
    else:
        assert target.preview_session_id is not None
        state = await _preview_state(target.preview_session_id, ids)
    _assert_characterization(
        FIXTURE_PATH,
        f"{cell}/{surface}",
        {
            "status": outcome["status"],
            "events": _tokens_of_a_cut_stream([_event(event, ids) for event in outcome["events"]]),
            "escaped": outcome["escaped"],
            "state": state,
            "clover": await _clover(db_session, target.user_id),
            "llm": fake.calls,
            "sentry": sentry,
            "scheduled": scheduled,
        },
    )


# ── background 일이 도는 순간의 요청 트랜잭션 ─────────────────────────────────────────────
#
# 턴은 커밋 뒤 조회(칸 서명·에필로그·상황 이미지 URL)가 연 트랜잭션을 반납한 다음 요약 접기를 예약한다. 요청 세션은 background
# 가 끝난 뒤 닫히므로, 반납이 빠지거나 조회가 그 뒤로 밀리면 접기의 요약 LLM 내내 커넥션을 쥔다. 예약된 일이 실행되는 순간
# 열린 루트 트랜잭션 수를 잰다. 방은 30턴이라 접기가 실제로 요약 LLM 을 부르고, 스토리 방은 칸 그림·엔딩(에필로그)까지
# 지나는 턴이다.


async def _fold_target(db_client: httpx.AsyncClient, db_session: AsyncSession, case: str) -> _Target:
    action, lane = case.split("-")
    room = await _open_room(db_client, db_session, turns=30, lane=lane)
    if lane == "story":
        # 보내기 31턴째·수정 30턴째에 각각 하나씩 엔딩 판정 차례가 오게 한다. 재생성은 엔딩을 다시 판정하지 않으므로
        # 이 문턱은 재생성 턴에 쓰이지 않는다.
        match_id = await _add_room_cell_and_endings(db_session, room.room_id, (1, 5))
    else:
        match_id = await _add_room_situational_image(db_session, room.room_id)
    method, path, body = _room_request(action, room.room_id, room.turns[30][0].id)
    return _Target(method, path, body, room.user_id, str(match_id), room_id=room.room_id)


@pytest.mark.parametrize(
    "case",
    ["send-story", "edit-story", "regenerate-story", "send-character", "edit-character", "regenerate-character"],
)
async def test_background_work_starts_with_no_request_transaction_open(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    target = await _fold_target(db_client, db_session, case)
    # 셋업이 같은 세션에 남긴 트랜잭션을 닫아 기준값을 0 으로 만든다(요청 세션이 곧 이 세션이다).
    await db_session.commit()
    seen: list[tuple[str, int]] = []
    fake = _MatrixLLM(_Script(), match_id=target.match_id, disconnect=asyncio.Event())

    with _open_transaction_probe() as open_sessions:
        original_add_task = BackgroundTasks.add_task

        def add_task(self: BackgroundTasks, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
            async def probe_then_run(*inner_args: Any, **inner_kwargs: Any) -> None:
                seen.append((func.__name__, len(open_sessions)))
                result = func(*inner_args, **inner_kwargs)
                if inspect.isawaitable(result):
                    await result

            original_add_task(self, probe_then_run, *args, **kwargs)

        monkeypatch.setattr(BackgroundTasks, "add_task", add_task)
        _override_llm_client(fake)
        try:
            response = await db_client.request(target.method, target.path, json=target.body)
        finally:
            _clear_llm_override()

    assert response.status_code == 200, response.text
    events = _parse_sse_events(response.text)
    assert events[-1]["type"] == "done"
    # 턴이 커밋 뒤 조회를 실제로 지났다 — 그림 URL(칸 서명·상황 이미지 URL)과, 스토리 방의 보내기·수정은 엔딩 에필로그.
    # 건너뛰었다면 "열린 트랜잭션 0" 은 그 조회가 연 트랜잭션을 반납하는지를 재지 않은 것이다. 재생성은 엔딩을 다시
    # 판정하지 않아 그림 URL 조회만 지난다.
    final = events[-1]["finalMessage"]
    assert final["imageId"] == target.match_id
    assert final["imageUrl"]
    if case in ("send-story", "edit-story"):
        assert any(event["type"] == "endingReached" and event.get("epilogue") for event in events)
    # 접기가 실제로 요약 LLM 을 불렀다 — 안 불렀다면 "열린 트랜잭션 0" 이 아무것도 재지 않은 것이다.
    assert ["generate_structured", "chat_memory_summary"] in fake.calls
    assert seen == [("fold_memory", 0)]


# ── 미리보기 판정 동시 실행 ───────────────────────────────────────────────────────────────


async def test_preview_runs_stat_and_media_judgments_concurrently(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """두 판정이 서로를 기다리는 가짜 — 차례로 부르면 먼저 불린 스탯 판정이 시간 초과로 실패해 스탯 변화와 그 뒤의 엔딩
    판정이 빠진다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_asset(db_session, owner_user_id=user.id, status=AssetStatus.READY)
    await db_session.commit()
    await _login_as(db_client, user.id)
    cell_id, payload = _preview_story_payload(asset.id)
    started = await db_client.post("/preview-sessions", json=payload)
    assert started.status_code == 201, started.text
    fake = _MatrixLLM(_Script(rendezvous=True), match_id=str(cell_id), disconnect=asyncio.Event())

    _override_llm_client(fake)
    try:
        response = await db_client.post(
            f"/preview-sessions/{started.json()['previewSessionId']}/messages", json={"content": "행복해지자"}
        )
    finally:
        _clear_llm_override()

    assert response.status_code == 200, response.text
    events = _parse_sse_events(response.text)
    assert [event["type"] for event in events if event["type"] != "token"] == ["statChange", "endingReached", "done"]
    assert events[-1]["finalMessage"]["imageId"] == str(cell_id)
