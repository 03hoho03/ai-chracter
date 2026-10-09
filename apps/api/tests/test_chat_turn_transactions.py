"""채팅 네 경로(보내기·수정·재생성·미리보기)가 LLM 을 기다리는 동안 DB 트랜잭션을 쥐지 않는지, 그리고 그렇게
쪼갠 뒤에도 사용자에게 나가는 SSE 이벤트와 저장되는 결과가 그대로인지를 고정한다.

LLM 응답은 수 초에서 수십 초가 걸린다. 그동안 요청 세션이 트랜잭션을 열어 두면 커넥션 하나를 통째로 쥐어, 동시에
진행할 수 있는 턴 수가 커넥션 풀 크기에 묶인다. 그래서 외부 호출 직전에는 요청 세션을 커밋으로 반납한다.

측정: 세션 트랜잭션 이벤트로 "지금 루트 트랜잭션이 열린 세션 수"를 유지하고(`_open_transaction_probe`), 가짜
LLM 이 호출되는 순간 그 수를 기록한다. 단언은 요청이 끝난 뒤에 한다 — 요약 접기는 예외를 전부 삼키므로 페이크
안에서 던지면 신호가 사라진다. `db_client` 는 테스트를 커넥션 하나에 묶어 `engine.pool.checkedout()` 이 늘 1이라
그 지표로는 아무것도 못 잰다. 실제 풀 지표와의 연결은 독립 엔진 세션으로 보내기 한 경로만 따로 확인한다.

이벤트·결과 기대값(`fixtures/chat_turn_sse_snapshot.json`)은 트랜잭션을 쪼개기 **전** 코드에서 같은 시나리오로
뜬 것이다. 새 코드로 다시 뜨면 같은 코드가 같은 값을 내므로 아무것도 증명하지 못한다 — 다시 뜨지 않는다. 값은
id·시각·서명 URL 의 호스트·쿼리만 지운다(id 는 처음 나온 순서의 번호로 바꿔 같은 id 가 같은 자리에 나오는지는 남긴다).
"""

import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.chat import router as chat_router
from api.chat import turn_settlement, turn_store
from api.chat.preview_session import get_preview_session
from api.chat.turn_settlement import TurnSettlement
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MemorySummaryResult,
    StatRuleJudgmentResult,
)
from api.core import clover, rate_limit_gate
from api.core.rate_limit_gate import ChatCharge
from api.core.config import settings
from api.db.models import (
    Asset,
    AssetKind,
    AssetStatus,
    CharacterImageExposure,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomStat,
    Content,
    ContentVersion,
    Ending,
    SituationalImage,
    StartingSetup,
    StatDef,
    StatRule,
    User,
)
from api.db.models.chat import DiscardedResponse, StoryEndingUnlock, StoryMediaExposure
from api.db.models.clover import CloverLedger
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    _add_named_media_cell,
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_user,
    _make_user_with_clover_lot,
    _open_room,
    _open_transaction_probe,
    _override_llm_client,
    _parse_sse_events,
)

SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "chat_turn_sse_snapshot.json"


class _ScriptedLLMClient(LLMClient):
    """호출 위치별 응답 큐를 차례로 내주고, 호출되는 순간 열린 세션 트랜잭션 수를 `(호출 위치, 수)` 로 남긴다.

    요약 접기(`MemorySummaryResult`)는 큐 없이 고정 요약을 돌려준다 — 접을 때가 된 방이면 턴 뒤에 오고, 아니면
    오지 않는다."""

    def __init__(self, open_sessions: set[int], *, tokens: list[str], structured: dict[str, list[Any]]) -> None:
        self._open_sessions = open_sessions
        self._tokens = tokens
        self._structured = {site: list(results) for site, results in structured.items()}
        self.calls: list[tuple[str, int]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append((usage.call_site, len(self._open_sessions)))
        for token in self._tokens:
            yield token

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.calls.append((usage.call_site, len(self._open_sessions)))
        if response_schema is MemorySummaryResult:
            return MemorySummaryResult(summary="요약")
        return self._structured[usage.call_site].pop(0)


@dataclass
class _Turn:
    """시나리오 한 개 — 보낼 요청과 판정 응답, 요청 뒤 저장 결과를 읽는 함수."""

    method: str
    path: str
    body: dict[str, object] | None
    structured: dict[str, list[Any]]
    read_state: Callable[[], Awaitable[dict[str, Any]]]
    tokens: list[str] = field(default_factory=lambda: ["오늘은 ", "비가 와."])


async def _room_state(db_session: AsyncSession, room_id: uuid.UUID) -> dict[str, Any]:
    room = (
        await db_session.execute(
            sa.select(
                ChatRoom.turn_count, ChatRoom.ending_reached, ChatRoom.ending_entity_id, ChatRoom.ending_reached_at_turn
            ).where(ChatRoom.id == room_id)
        )
    ).one()
    messages = (
        await db_session.execute(
            sa.select(ChatMessage.role, ChatMessage.content, ChatMessage.image_id)
            .where(ChatMessage.chat_room_id == room_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    ).all()
    stats = (
        await db_session.execute(
            sa.select(ChatRoomStat.stat_entity_id, ChatRoomStat.current_value)
            .where(ChatRoomStat.chat_room_id == room_id)
            .order_by(ChatRoomStat.stat_entity_id)
        )
    ).all()
    user_id = await db_session.scalar(sa.select(ChatRoom.user_id).where(ChatRoom.id == room_id))
    counts = {}
    for name, model in (
        ("characterExposures", CharacterImageExposure),
        ("storyExposures", StoryMediaExposure),
        ("endingUnlocks", StoryEndingUnlock),
    ):
        counts[name] = await db_session.scalar(
            sa.select(sa.func.count()).select_from(model).where(model.user_id == user_id)
        )
    return {
        "turnCount": room.turn_count,
        "endingReached": room.ending_reached,
        "endingId": str(room.ending_entity_id) if room.ending_entity_id else None,
        "endingReachedAtTurn": room.ending_reached_at_turn,
        "messages": [
            {"role": m.role.value, "content": m.content, "imageId": str(m.image_id) if m.image_id else None}
            for m in messages
        ],
        "stats": [{"id": str(s.stat_entity_id), "value": str(s.current_value)} for s in stats],
        **counts,
    }


async def _add_situational_image(db_session: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    version_id = await db_session.scalar(sa.select(ChatRoom.content_version_id).where(ChatRoom.id == room_id))
    assert version_id is not None
    asset = Asset(
        owner_user_id=user_id,
        storage_key=f"assets/situational-image/{uuid.uuid4()}.webp",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    image = SituationalImage(
        entity_id=uuid.uuid4(),
        content_version_id=version_id,
        image_asset_id=asset.id,
        trigger_condition="둘이 골목에서 마주칠 때",
        order=0,
    )
    db_session.add(image)
    await db_session.commit()
    return image.entity_id


async def _story_extras(db_session: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """스토리 방에 칸 하나와 엔딩 둘(게이트 1, 규칙 없음), 스탯 규칙 하나를 더한다. 칸 id 를 돌려준다."""
    version_id, setup_entity_id = (
        await db_session.execute(
            sa.select(ChatRoom.content_version_id, ChatRoom.starting_setup_entity_id).where(ChatRoom.id == room_id)
        )
    ).one()
    setup = await db_session.scalar(
        sa.select(StartingSetup).where(
            StartingSetup.content_version_id == version_id, StartingSetup.entity_id == setup_entity_id
        )
    )
    assert setup is not None
    stat_def = await db_session.scalar(sa.select(StatDef).where(StatDef.starting_setup_id == setup.id))
    assert stat_def is not None
    # 기대값(73 → 80)을 만드는 둘째 규칙 a2(+7). 방 팩토리의 규칙 a1(+5)은 발동시키지 않는다.
    db_session.add(StatRule(entity_id=uuid.uuid4(), stat_def_id=stat_def.id, condition="떠나자고 한다", delta=7, order=1))
    cell, _ = await _add_named_media_cell(
        db_session, version_id, user_id, "민아", "교실", situation_description="창가에서 웃는다"
    )
    for order, epilogue in ((1, "첫 엔딩 에필로그."), (2, "그렇게 마을을 떠났다.")):
        db_session.add(
            Ending(
                entity_id=uuid.uuid4(),
                starting_setup_id=setup.id,
                name=f"엔딩{order}",
                turn_count_gate=1,
                judgment_prompt=f"떠났는가? ({order})",
                epilogue=epilogue,
                order=order,
            )
        )
    await db_session.commit()
    return str(cell.entity_id)


def _story_judgments(cell_id: str, *, with_stats: bool) -> dict[str, list[Any]]:
    structured: dict[str, list[Any]] = {
        "chat_media_book_image": [ImageMatchJudgmentResult(matched_image_entity_id=cell_id)]
    }
    if with_stats:
        structured["chat_stat_judgment"] = [StatRuleJudgmentResult(fired_rule_ids=["a2"])]
        structured["chat_ending_judgment"] = [
            EndingJudgmentResult(triggered=False),
            EndingJudgmentResult(triggered=True),
        ]
    return structured


async def _send_character(db_client: httpx.AsyncClient, db_session: AsyncSession) -> _Turn:
    # 30턴 = 요약 접기가 도는 방. 접기 호출도 외부 호출이라 같이 잰다.
    room = await _open_room(db_client, db_session, turns=30)
    image_id = await _add_situational_image(db_session, room.room_id, room.user_id)
    return _Turn(
        "POST",
        f"/chat-rooms/{room.room_id}/messages",
        {"content": "골목으로 가자"},
        {"chat_situational_image": [ImageMatchJudgmentResult(matched_image_entity_id=str(image_id))]},
        lambda: _room_state(db_session, room.room_id),
    )


async def _send_story(db_client: httpx.AsyncClient, db_session: AsyncSession) -> _Turn:
    room = await _open_room(db_client, db_session, turns=0, lane="story")
    cell_id = await _story_extras(db_session, room.room_id, room.user_id)
    return _Turn(
        "POST",
        f"/chat-rooms/{room.room_id}/messages",
        {"content": "마을을 떠나자"},
        _story_judgments(cell_id, with_stats=True),
        lambda: _room_state(db_session, room.room_id),
    )


async def _edit_story(db_client: httpx.AsyncClient, db_session: AsyncSession) -> _Turn:
    room = await _open_room(db_client, db_session, turns=1, lane="story")
    cell_id = await _story_extras(db_session, room.room_id, room.user_id)
    return _Turn(
        "PATCH",
        f"/chat-rooms/{room.room_id}/messages/{room.turns[1][0].id}",
        {"content": "고쳐 말하면, 마을을 떠나자"},
        _story_judgments(cell_id, with_stats=True),
        lambda: _room_state(db_session, room.room_id),
    )


async def _regenerate_character(db_client: httpx.AsyncClient, db_session: AsyncSession) -> _Turn:
    room = await _open_room(db_client, db_session, turns=1)
    image_id = await _add_situational_image(db_session, room.room_id, room.user_id)
    return _Turn(
        "POST",
        f"/chat-rooms/{room.room_id}/regenerate",
        None,
        {"chat_situational_image": [ImageMatchJudgmentResult(matched_image_entity_id=str(image_id))]},
        lambda: _room_state(db_session, room.room_id),
    )


async def _regenerate_story(db_client: httpx.AsyncClient, db_session: AsyncSession) -> _Turn:
    room = await _open_room(db_client, db_session, turns=1, lane="story")
    cell_id = await _story_extras(db_session, room.room_id, room.user_id)
    return _Turn(
        "POST",
        f"/chat-rooms/{room.room_id}/regenerate",
        None,
        _story_judgments(cell_id, with_stats=False),
        lambda: _room_state(db_session, room.room_id),
    )


async def _preview_story(db_client: httpx.AsyncClient, db_session: AsyncSession) -> _Turn:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    stat_id = str(uuid.uuid4())
    payload: dict[str, object] = {
        "name": "잃어버린 도시",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "promptTemplate": "basic",
        "settingText": "세계관 설명",
        "developmentExample": None,
        "customPrompt": None,
        "startingSetups": [
            {
                "id": str(uuid.uuid4()),
                "name": "시작설정1",
                "prologue": "프롤로그",
                "openingMessage": "어서 와.",
                "playguide": None,
                "suggestedReplies": [],
                "statDefs": [
                    {
                        "id": stat_id,
                        "name": "체력",
                        "icon": "heart",
                        "color": "rose",
                        "minValue": 0,
                        "maxValue": 100,
                        "initialValue": 50,
                        "unit": None,
                        "description": "체력 스탯",
                        # 기대값(50 → 90)을 만드는 규칙 a1(+40).
                        "rules": [{"id": str(uuid.uuid4()), "condition": "행복해진다", "delta": 40}],
                    }
                ],
                "endings": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "해피엔딩",
                        "turnCountGate": 1,
                        "judgmentPrompt": "행복한 결말에 도달했는가",
                        "epilogue": "모두가 행복하게 살았다.",
                        "hint": None,
                        "statRules": [],
                    }
                ],
            }
        ],
        "keywordNotes": [],
        "shortcuts": [],
        "description": "상세 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }
    started = await db_client.post("/preview-sessions", json=payload)
    assert started.status_code == 201, started.text
    session_id = started.json()["previewSessionId"]

    async def _read_state() -> dict[str, Any]:
        state = await get_preview_session(session_id)
        assert state is not None
        return {
            "turnCount": state.turn_count,
            "endingReached": state.ending_reached,
            "stats": {key: value for key, value in sorted(state.stats.items())},
            "messages": [
                {"role": m.role.value, "content": m.content, "imageId": str(m.image_id) if m.image_id else None}
                for m in state.messages
            ],
        }

    return _Turn(
        "POST",
        f"/preview-sessions/{session_id}/messages",
        {"content": "행복해지자"},
        {
            "preview_stat_judgment": [StatRuleJudgmentResult(fired_rule_ids=["a1"])],
            "preview_ending_judgment": [EndingJudgmentResult(triggered=True)],
        },
        _read_state,
    )


_SCENARIOS: dict[str, Callable[[httpx.AsyncClient, AsyncSession], Awaitable[_Turn]]] = {
    "send-character": _send_character,
    "send-story": _send_story,
    "edit-story": _edit_story,
    "regenerate-character": _regenerate_character,
    "regenerate-story": _regenerate_story,
    "preview-story": _preview_story,
}

# 시나리오마다 외부 호출이 실제로 그 자리들을 지나는지 — 이게 빠지면 "열린 트랜잭션 0"이 호출이 없어서 참일 수 있다.
_EXPECTED_CALL_SITES = {
    "send-character": ["chat_generate", "chat_situational_image", "chat_memory_summary"],
    "send-story": [
        "chat_generate",
        "chat_stat_judgment",
        "chat_media_book_image",
        "chat_ending_judgment",
        "chat_ending_judgment",
    ],
    "edit-story": [
        "chat_generate",
        "chat_stat_judgment",
        "chat_media_book_image",
        "chat_ending_judgment",
        "chat_ending_judgment",
    ],
    "regenerate-character": ["chat_generate", "chat_situational_image"],
    "regenerate-story": ["chat_generate", "chat_media_book_image"],
    "preview-story": ["preview_generate", "preview_stat_judgment", "preview_ending_judgment"],
}


async def _run(
    db_client: httpx.AsyncClient, db_session: AsyncSession, case: str
) -> tuple[list[tuple[str, int]], list[dict[str, Any]], dict[str, Any]]:
    turn = await _SCENARIOS[case](db_client, db_session)
    # 셋업이 같은 세션에 남긴 트랜잭션을 닫아 기준값을 0 으로 만든다(요청 세션이 곧 이 세션이다).
    await db_session.commit()
    with _open_transaction_probe() as open_sessions:
        fake = _ScriptedLLMClient(open_sessions, tokens=turn.tokens, structured=turn.structured)
        _override_llm_client(fake)
        try:
            response = await db_client.request(turn.method, turn.path, json=turn.body)
        finally:
            _clear_llm_override()
    assert response.status_code == 200, response.text
    return fake.calls, _parse_sse_events(response.text), await turn.read_state()


@pytest.mark.parametrize("case", list(_SCENARIOS))
async def test_no_transaction_is_open_while_waiting_for_the_llm(
    db_client: httpx.AsyncClient, db_session: AsyncSession, case: str
) -> None:
    calls, _, _ = await _run(db_client, db_session, case)

    assert [site for site, _ in calls] == _EXPECTED_CALL_SITES[case]
    assert [(site, count) for site, count in calls if count != 0] == []


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _normalize(value: Any, ids: dict[str, str]) -> Any:
    """id 는 처음 나온 순서의 번호로, 시각은 자리표시로, 서명 URL 은 경로만 남긴다(호스트는 테스트마다 뜨는
    S3 흉내 서버의 포트가, 쿼리는 서명 시각이 바뀌고, 버킷 이름은 환경 설정이다)."""

    def _ids(text: str) -> str:
        return _UUID.sub(lambda m: ids.setdefault(m.group(0), f"<id{len(ids) + 1}>"), text)

    if isinstance(value, dict):
        return {
            _ids(key): "<time>" if key == "createdAt" else _normalize(item, ids) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize(item, ids) for item in value]
    if isinstance(value, str):
        if value.startswith("http"):
            value = urlsplit(value).path.replace(settings.s3_bucket_name, "<bucket>", 1)
        return _ids(value)
    return value


@pytest.mark.parametrize("case", list(_SCENARIOS))
async def test_events_and_saved_turn_match_the_snapshot_taken_before_the_split(
    db_client: httpx.AsyncClient, db_session: AsyncSession, case: str
) -> None:
    _, events, state = await _run(db_client, db_session, case)

    ids: dict[str, str] = {}
    actual = {"events": _normalize(events, ids), "state": _normalize(state, ids)}
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))[case]
    assert actual == expected


# ── 실제 커넥션 풀로 한 번 더 ───────────────────────────────────────────────────────────
#
# 위 프로브의 "열린 루트 트랜잭션 0"이 정말 "풀에서 빌린 커넥션 0"인지를, 테스트 픽스처를 거치지 않는 실제 엔진 세션으로
# 보내기 한 경로에서 확인한다. 이 테스트가 쓴 행은 롤백되지 않으므로 표지 도메인 회원 것만 직접 지운다.

_MARKER_DOMAIN = "chat-turn-transactions.test"


@pytest_asyncio.fixture
async def independent_session_factory(
    db_engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory
    async with factory() as cleanup:
        user_ids = (await cleanup.scalars(sa.select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if user_ids:
            room_ids = (await cleanup.scalars(sa.select(ChatRoom.id).where(ChatRoom.user_id.in_(user_ids)))).all()
            content_ids = (
                await cleanup.scalars(sa.select(Content.id).where(Content.creator_user_id.in_(user_ids)))
            ).all()
            version_ids = (
                await cleanup.scalars(sa.select(ContentVersion.id).where(ContentVersion.content_id.in_(content_ids)))
            ).all()
            await cleanup.execute(sa.delete(ChatMessage).where(ChatMessage.chat_room_id.in_(room_ids)))
            await cleanup.execute(sa.delete(ChatRoom).where(ChatRoom.id.in_(room_ids)))
            await cleanup.execute(
                sa.delete(CharacterVersionDetail).where(CharacterVersionDetail.content_version_id.in_(version_ids))
            )
            await cleanup.execute(
                sa.update(Content).where(Content.id.in_(content_ids)).values(current_published_version_id=None)
            )
            await cleanup.execute(sa.delete(ContentVersion).where(ContentVersion.id.in_(version_ids)))
            await cleanup.execute(sa.delete(Content).where(Content.id.in_(content_ids)))
            await cleanup.execute(sa.delete(Asset).where(Asset.owner_user_id.in_(user_ids)))
            await cleanup.execute(sa.delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


class _PoolRecordingLLMClient(LLMClient):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self.checked_out: list[int] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.checked_out.append(self._engine.pool.checkedout())  # type: ignore[attr-defined]
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("이 시나리오에는 판정 호출이 없다")


async def test_send_holds_no_pooled_connection_while_streaming_on_a_real_engine(
    api_client: httpx.AsyncClient,
    db_engine: AsyncEngine,
    independent_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with independent_session_factory() as session:
        user = _make_user(email=f"{uuid.uuid4()}@{_MARKER_DOMAIN}", rate_limit_exempt=True)
        session.add(user)
        await session.flush()
        genre = await _get_genre(session)
        content = await _make_published_character(session, creator_user_id=user.id, genre_id=genre.id)
        assert content.current_published_version_id is not None
        room = ChatRoom(user_id=user.id, content_id=content.id, content_version_id=content.current_published_version_id)
        session.add(room)
        await session.flush()
        session.add(
            ChatMessage(
                chat_room_id=room.id,
                role=ChatMessageRole.ASSISTANT,
                content="인트로",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()
        user_id, room_id = user.id, room.id

    api_client.cookies.clear()
    await _login_as(api_client, user_id)
    baseline = db_engine.pool.checkedout()  # type: ignore[attr-defined]
    fake = _PoolRecordingLLMClient(db_engine)
    _override_llm_client(fake)
    try:
        response = await api_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()
        api_client.cookies.clear()

    assert response.status_code == 200, response.text
    assert [event["type"] for event in _parse_sse_events(response.text)][-1] == "done"
    assert fake.checked_out == [baseline]


# ── 턴 도중 방이 지워지면 ─────────────────────────────────────────────────────────────
#
# 생성을 기다리는 동안 트랜잭션도 방 행 잠금도 쥐지 않으므로, 그사이 사용자가 방을 지울 수 있다(방 삭제는 언제나
# 성공해야 해서 턴 락 대상이 아니다). 그러면 쓰기 구간은 아무것도 쓰지 않고 오류 이벤트로 끝난다. 클로버는 돌려주지
# 않는다 — 사용자가 지운 것이고 LLM 은 이미 탔다.


class _RoomDeletingLLMClient(LLMClient):
    """생성 도중 같은 사용자가 방 삭제 API 를 부른다."""

    def __init__(self, client: httpx.AsyncClient, room_id: uuid.UUID) -> None:
        self._client = client
        self._room_id = room_id
        self.deleted_status: int | None = None

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield "지워지기 "
        self.deleted_status = (await self._client.delete(f"/chat-rooms/{self._room_id}")).status_code
        yield "직전의 응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("방이 지워진 턴은 판정까지 가더라도 쓰지 않는다 — 이 시나리오엔 판정 대상이 없다")


@pytest.mark.parametrize("action", ["send", "regenerate"])
async def test_room_deleted_during_generation_ends_with_an_error_and_no_refund(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    action: str,
) -> None:
    user = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    room = await _open_room(db_client, db_session, turns=1, user=user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    fake = _RoomDeletingLLMClient(db_client, room.room_id)
    _override_llm_client(fake)
    try:
        with caplog.at_level(logging.WARNING, logger=turn_store.__name__):
            if action == "send":
                resp = await db_client.post(f"/chat-rooms/{room.room_id}/messages", json={"content": "안녕"})
            else:
                resp = await db_client.post(f"/chat-rooms/{room.room_id}/regenerate")
    finally:
        _clear_llm_override()

    assert fake.deleted_status == 204
    assert resp.status_code == 200
    assert [event["type"] for event in _parse_sse_events(resp.text)] == ["token", "token", "error"]
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(ChatRoom).where(ChatRoom.id == room.room_id)) == 0
    assert any(str(room.room_id) in record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING)
    await db_session.refresh(user)
    assert user.clover_balance == 100 - clover.CHAT_TURN_COST
    kinds = (await db_session.scalars(sa.select(CloverLedger.kind).where(CloverLedger.user_id == user.id))).all()
    assert list(kinds) == ["chat_spend"]


# ── 쓰기 구간이 중간에 실패하면 ───────────────────────────────────────────────────────────
#
# 쓰기 구간(응답 메시지·turn_count·노출·스탯·엔딩, 재생성은 옛 응답 삭제·새 응답)은 커밋 한 번이다. 그 뒷부분에서 진짜
# DB 오류가 나면 앞부분도 같이 사라져야 한다 — 쓰기 구간 중간에 커밋이 끼면 응답만 남고 스탯은 안 바뀐 턴이 생긴다.
# 실패를 일으키는 자리는 SAVEPOINT 로 감싼 노출 기록 바깥이어야 한다(그 안의 실패는 그 기록만 포기하고 지나간다).


class _AnswerAllLLMClient(LLMClient):
    """생성은 고정 응답, 판정은 스탯만 바꾸고(방 팩토리 스탯의 규칙 a1) 엔딩·그림은 없다고 답한다."""

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield "새 응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=["a1"])
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=False)
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=None)
        return MemorySummaryResult(summary="요약")


async def _request_failure(client: httpx.AsyncClient, path: str, body: dict[str, object] | None) -> BaseException:
    """요청이 앱 예외로 끝나면 그 예외를 돌려준다. `ASGITransport` 는 응답을 다 모은 뒤에야 돌려주므로 예외 앞에 나간
    토큰 이벤트는 여기서 볼 수 없다 — 예외가 클라이언트까지 올라왔다는 것이 "done·error 이벤트로 마무리되지 않았다"는
    뜻이다."""
    try:
        response = await client.post(path, json=body)
    except Exception as exc:
        return exc
    raise AssertionError(f"쓰기 구간 실패가 요청을 끝내지 않았다: {response.status_code} {response.text!r}")


def _leaf_exceptions(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in _leaf_exceptions(inner)]
    return [exc]


@pytest.mark.usefixtures("committing_request_session")
async def test_send_write_failure_after_the_stat_write_saves_nothing_of_the_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 기준(결과를 보기 전에 적었다): 스탯 쓰기 뒤에 진짜 DB 오류(외래 키 위반)가 나면 이번 턴의 AI 응답 메시지,
    올라간 `turn_count`, 바뀐 스탯 값 중 **하나라도** 저장돼 있으면 실패다. 보내기 전에 커밋한 사용자 메시지는 남는 것이
    맞다.

    함께 고정하는 동작: 예외가 제너레이터 밖으로 나가 스트림이 done·error 이벤트 없이 끊기고, 응답이 저장되지 않았으므로
    정산 가드가 클로버를 되돌린다(원래 예외는 그대로 올라간다)."""
    user = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    room = await _open_room(db_client, db_session, turns=1, lane="story", user=user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    before = await _room_state(db_session, room.room_id)

    write_room_stat = turn_store._write_room_stat

    def _write_then_break(
        db: AsyncSession, room_id: uuid.UUID, stat_rows: dict[str, ChatRoomStat], stat_id: str, value: float
    ) -> None:
        write_room_stat(db, room_id, stat_rows, stat_id, value)
        # 없는 방을 가리키는 스탯 행 — 쓰기 구간의 커밋에서 외래 키 위반으로 터진다.
        db.add(ChatRoomStat(chat_room_id=uuid.uuid4(), stat_entity_id=uuid.uuid4(), current_value=Decimal(0)))

    monkeypatch.setattr(turn_store, "_write_room_stat", _write_then_break)
    _override_llm_client(_AnswerAllLLMClient())
    try:
        exc = await _request_failure(db_client, f"/chat-rooms/{room.room_id}/messages", {"content": "마을을 떠나자"})
    finally:
        _clear_llm_override()

    assert any(isinstance(leaf, IntegrityError) for leaf in _leaf_exceptions(exc)), exc
    after = await _room_state(db_session, room.room_id)
    assert after["messages"] == [*before["messages"], {"role": "user", "content": "마을을 떠나자", "imageId": None}]
    assert after["turnCount"] == before["turnCount"]
    assert after["stats"] == before["stats"]
    await db_session.refresh(user)
    assert user.clover_balance == 100
    kinds = (await db_session.scalars(sa.select(CloverLedger.kind).where(CloverLedger.user_id == user.id))).all()
    assert sorted(kinds) == ["chat_refund", "chat_spend"]


@pytest.mark.usefixtures("committing_request_session")
async def test_regenerate_write_failure_keeps_the_old_response(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 기준(결과를 보기 전에 적었다): 재생성 쓰기 구간에서 진짜 DB 오류(폐기 기록의 CHECK 위반)가 나면 옛 응답이
    그대로 있어야 하고, 새 응답과 폐기 기록은 없어야 한다 — 옛 응답이 지워져 있거나 새 응답·폐기 기록이 하나라도 저장돼
    있으면 실패다.

    함께 고정하는 동작: 예외가 제너레이터 밖으로 나가 스트림이 done·error 이벤트 없이 끊기고, 새 응답이 저장되지
    않았으므로 정산 가드가 클로버를 되돌린다."""
    user = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    room = await _open_room(db_client, db_session, turns=1, user=user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    before = await _room_state(db_session, room.room_id)

    def _breaking_discarded_response(**fields: Any) -> DiscardedResponse:
        # 지운 응답 수 0 은 CHECK(1 이상) 위반 — 쓰기 구간의 커밋에서 터진다.
        return DiscardedResponse(**{**fields, "discarded_count": 0})

    monkeypatch.setattr(chat_router, "DiscardedResponse", _breaking_discarded_response)
    _override_llm_client(_AnswerAllLLMClient())
    try:
        exc = await _request_failure(db_client, f"/chat-rooms/{room.room_id}/regenerate", None)
    finally:
        _clear_llm_override()

    assert any(isinstance(leaf, IntegrityError) for leaf in _leaf_exceptions(exc)), exc
    after = await _room_state(db_session, room.room_id)
    assert after["messages"] == before["messages"]
    assert after["turnCount"] == before["turnCount"]
    discarded = await db_session.scalar(
        sa.select(sa.func.count()).select_from(DiscardedResponse).where(DiscardedResponse.user_id == user.id)
    )
    assert discarded == 0
    await db_session.refresh(user)
    assert user.clover_balance == 100
    kinds = (await db_session.scalars(sa.select(CloverLedger.kind).where(CloverLedger.user_id == user.id))).all()
    assert sorted(kinds) == ["chat_refund", "chat_spend"]


async def test_settlement_of_a_failed_write_releases_the_requests_room_lock_before_checking(
    independent_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 기준(결과를 보기 전에 적었다): 쓰기 구간이 방 행을 `FOR NO KEY UPDATE` 로 잠그고 응답을 올린 채(커밋 전) 끝나면,
    정산이 상한(여기서는 2초) 안에 응답이 없음을 확인하고 한 번 환급해야 한다. 정산의 `FOR SHARE` 가 자기 요청의 잠금을
    기다리면 상한을 다 쓰고 0번이다. 독립 커넥션이라야 두 세션이 잠금을 다툰다.

    요청 세션의 트랜잭션이 아직 열려 있는 경우다 — DB 오류는 SQLAlchemy 가 이미 되감지만, 쓰기 구간의 파이썬 예외는
    트랜잭션을 연 채 정산에 닿는다."""
    async with independent_session_factory() as session:
        user = _make_user(email=f"{uuid.uuid4()}@{_MARKER_DOMAIN}")
        session.add(user)
        await session.flush()
        genre = await _get_genre(session)
        content = await _make_published_character(session, creator_user_id=user.id, genre_id=genre.id)
        assert content.current_published_version_id is not None
        room = ChatRoom(user_id=user.id, content_id=content.id, content_version_id=content.current_published_version_id)
        session.add(room)
        await session.commit()
        user_id, room_id = user.id, room.id

    refunds: list[int] = []

    async def _fake_refund(*_args: Any, amount: int, **_kwargs: Any) -> None:
        refunds.append(amount)

    monkeypatch.setattr(clover, "refund_spend_in_new_transaction", _fake_refund)
    monkeypatch.setattr(turn_settlement, "SETTLE_TIMEOUT_SECONDS", 2.0)
    settlement = TurnSettlement(
        charge=ChatCharge(source="clover", clover_amount=clover.CHAT_TURN_COST, spend_ledger_id=uuid.uuid4()),
        user_id=user_id,
        session_factory=independent_session_factory,
    )
    reply_id = uuid.uuid4()

    async with independent_session_factory() as request_session:
        locked = await request_session.scalar(
            sa.select(ChatRoom.id).where(ChatRoom.id == room_id).with_for_update(key_share=True)
        )
        assert locked == room_id
        request_session.add(
            ChatMessage(id=reply_id, chat_room_id=room_id, role=ChatMessageRole.ASSISTANT, content="응답")
        )
        await request_session.flush()
        settlement.set_pending_message(request_session, room_id, reply_id)

        await settlement.refund_if_unsettled()

    assert refunds == [clover.CHAT_TURN_COST]
    async with independent_session_factory() as check:
        assert await check.get(ChatMessage, reply_id) is None
