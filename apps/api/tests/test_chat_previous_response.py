"""재생성이 밀어낸 직전 응답 하나를 보관하고, 사용자가 그 응답으로 되돌리는지.

규칙(결과를 보기 전에 적었다):
- 재생성이 성공하면 밀어낸 응답의 원래 id·시각·본문·그림을 방당 한 행에 보관한다(이미 있으면 덮는다). 옛 응답을 지우는 쓰기
  구간과 같은 트랜잭션이라, 생성·정책 실패로 끝난 재생성은 보관을 바꾸지 않는다.
- 되돌리기(`POST …/messages/{지금 응답 id}/restore-previous`)는 보관한 응답을 원래 id·시각으로 다시 넣고 지금 응답을 보관으로
  옮긴다(맞바꾸기). 같은 요청이 두 번 오면 두 번째는 409 다. 보관 행이 지금 응답을 가리키고 그 응답이 방의 마지막 메시지일
  때만 되돌리고, 아니면 409 `PREVIOUS_RESPONSE_UNAVAILABLE` 이며 마지막 메시지를 가리키지 않는 낡은 보관 행은 그때 지운다.
- 되돌리기는 차감·무료분·분당 상한·LLM 을 지나지 않고 턴 기록을 쓰지 않는다. 진행 중 턴이 있으면 409, 이용제한 작품의 방에서도
  된다. 폐기 기록에는 `undo` 로 남는다.
- 스탯은 지금 응답의 턴 효과를 되돌린 값 위에 되살린 응답의 턴 효과를 다시 얹는다. 지금 응답과 되살릴 응답의 턴 기록이 둘 다
  있고, 둘 다 엔딩이 없고, 방이 엔딩 전이고, 그 턴이 방의 마지막 턴일 때만이다. 지금 정의에 없는 스탯은 쓰지 않는다. 재판정
  없이 효과를 이어받은 재생성이면 결과가 지금 값과 같다.
- 요약은 두 응답 중 앞선 키부터 되감는다(덮던 스냅샷과 그 장면 기억이 사라지고 `memory_version` 이 오른다).
- 보내기·수정·메시지 삭제·초기화는 같은 커밋에서 보관 행을 지운다. 방 삭제·탈퇴는 방 FK 의 CASCADE 가 지운다 — 이 테이블을
  모르는 옛 이미지의 방 삭제도 실패하지 않는다.

방은 판정 스탯 "신뢰"(73, 규칙 a1 +5·a2 -2)와 카운터 "남은 날"(30, 턴마다 -1)을 가진 스토리 방이다."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.withdrawal import erase_account
from api.chat.prompt_builder import EndingJudgmentResult, ImageMatchJudgmentResult, StatRuleJudgmentResult
from api.core import clover, rate_limit_gate
from api.core.redis import redis_client
from api.db.models import (
    ChatMessage,
    ChatMessageRole,
    ChatPreviousResponse,
    ChatRoom,
    ChatRoomMemorySnapshot,
    ChatRoomStat,
    ChatTurn,
    Content,
    DiscardedResponse,
    ModerationStatus,
    StatDef,
    User,
)
from api.db.models.chat import ChatMemoryEpisode
from api.db.models.clover import CloverLedger
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMPolicyViolationError
from factories import (
    Room,
    _clear_llm_override,
    _login_as,
    _make_memory_episode,
    _make_user,
    _make_user_with_clover_lot,
    _NeverCalledLLMClient,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
    _stat_values,
    _Stats,
    _story_room,
)

_UNAVAILABLE = {"detail": {"code": "PREVIOUS_RESPONSE_UNAVAILABLE"}}


class _LLM(LLMClient):
    """생성은 `reply` 를 내거나 `generation_error` 를 올린다. 스탯 판정은 `fired` 규칙을 고르거나 `stat_error` 면 실패한다.
    엔딩·그림 판정은 아무것도 고르지 않는다."""

    def __init__(
        self,
        reply: str,
        fired: list[str] | None = None,
        *,
        stat_error: bool = False,
        generation_error: Exception | None = None,
    ) -> None:
        self._reply = reply
        self._fired = fired or []
        self._stat_error = stat_error
        self._generation_error = generation_error

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        if self._generation_error is not None:
            raise self._generation_error
        yield self._reply

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            if self._stat_error:
                raise LLMClientError("판정 실패")
            return StatRuleJudgmentResult(fired_rule_ids=self._fired)
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=False)
        assert response_schema is ImageMatchJudgmentResult
        return ImageMatchJudgmentResult(matched_image_entity_id=None)


async def _stream(client: httpx.AsyncClient, method: str, path: str, body: object, fake: LLMClient) -> list[str]:
    _override_llm_client(fake)
    try:
        response = await client.request(method, path, json=body)
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    return [event["type"] for event in _parse_sse_events(response.text)]


async def _send(client: httpx.AsyncClient, room: Room, fake: _LLM) -> None:
    assert (await _stream(client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "말"}, fake))[-1] == "done"


async def _regenerate(client: httpx.AsyncClient, room: Room, fake: _LLM) -> list[str]:
    return await _stream(client, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, fake)


async def _restore(
    client: httpx.AsyncClient, room: Room, message_id: uuid.UUID, *, message_limit: int | None = None
) -> httpx.Response:
    """되돌리기 요청. LLM 이 불리면 그 자체가 실패가 되도록 끼워 둔다."""
    query = f"?messageLimit={message_limit}" if message_limit is not None else ""
    _override_llm_client(_NeverCalledLLMClient())
    try:
        return await client.post(f"/chat-rooms/{room.room_id}/messages/{message_id}/restore-previous{query}")
    finally:
        _clear_llm_override()


_Message = tuple[uuid.UUID, ChatMessageRole, str, datetime, uuid.UUID | None]


async def _messages(db_session: AsyncSession, room: Room) -> list[_Message]:
    rows = (
        await db_session.execute(
            sa.select(ChatMessage.id, ChatMessage.role, ChatMessage.content, ChatMessage.created_at, ChatMessage.image_id)
            .where(ChatMessage.chat_room_id == room.room_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    ).all()
    return [(row.id, row.role, row.content, row.created_at, row.image_id) for row in rows]


_Kept = tuple[uuid.UUID, uuid.UUID, datetime, str, uuid.UUID | None]


async def _kept(db_session: AsyncSession, room: Room) -> _Kept | None:
    """보관 행(밀어낸 응답 id, 원래 id, 원래 시각, 본문, 그림) 또는 None."""
    row = (
        await db_session.execute(
            sa.select(
                ChatPreviousResponse.replaced_by_message_id,
                ChatPreviousResponse.message_id,
                ChatPreviousResponse.message_created_at,
                ChatPreviousResponse.content,
                ChatPreviousResponse.image_id,
            ).where(ChatPreviousResponse.chat_room_id == room.room_id)
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1], row[2], row[3], row[4])


async def _previous_response_for(client: httpx.AsyncClient, room: Room) -> object:
    response = await client.get(f"/chat-rooms/{room.room_id}")
    assert response.status_code == 200, response.text
    return response.json()["previousResponseFor"]


async def _record(db_session: AsyncSession, message_id: uuid.UUID) -> ChatTurn | None:
    db_session.expire_all()
    record: ChatTurn | None = await db_session.scalar(
        sa.select(ChatTurn).where(ChatTurn.assistant_message_id == message_id)
    )
    return record


async def _regenerated_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[Room, _Stats, _Message, _Message]:
    """한 턴(신뢰 +5)을 보내고 재생성(신뢰 -2)한 방. (방, 스탯, 밀려난 응답, 지금 응답)."""
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, room, _LLM("지킨 응답", ["a1"]))
    original = (await _messages(db_session, room))[-1]
    await _regenerate(db_client, room, _LLM("어긴 응답", ["a2"]))
    current = (await _messages(db_session, room))[-1]
    return room, stats, original, current


# ── 보관 ─────────────────────────────────────────────────────────────────────────────────


async def test_regeneration_keeps_the_replaced_reply_with_its_original_id_time_and_picture(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, room, _LLM("지킨 응답", ["a1"]))
    assert await _kept(db_session, room) is None
    assert await _previous_response_for(db_client, room) is None
    picture = uuid.uuid4()
    original = (await _messages(db_session, room))[-1]
    await db_session.execute(sa.update(ChatMessage).where(ChatMessage.id == original[0]).values(image_id=picture))
    await db_session.commit()

    await _regenerate(db_client, room, _LLM("어긴 응답", ["a2"]))

    messages = await _messages(db_session, room)
    current = messages[-1]
    assert current[0] != original[0] and current[2] == "어긴 응답"
    assert original[0] not in {message[0] for message in messages}
    assert await _kept(db_session, room) == (current[0], original[0], original[3], "지킨 응답", picture)
    assert await _previous_response_for(db_client, room) == str(current[0])


async def test_regenerating_again_keeps_only_the_reply_it_just_replaced(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _, _, first_replacement = await _regenerated_room(db_client, db_session)

    await _regenerate(db_client, room, _LLM("셋째 응답", []))

    current = (await _messages(db_session, room))[-1]
    kept = await _kept(db_session, room)
    assert kept is not None
    assert (kept[0], kept[1], kept[3]) == (current[0], first_replacement[0], "어긴 응답")


_FAILED_GENERATIONS = [
    pytest.param(LLMClientError("생성 실패"), id="generation-error"),
    pytest.param(LLMPolicyViolationError("blocked"), id="policy-violation"),
]


@pytest.mark.parametrize("error", _FAILED_GENERATIONS)
async def test_a_failed_regeneration_leaves_the_kept_reply_as_it_was(
    db_client: httpx.AsyncClient, db_session: AsyncSession, error: Exception
) -> None:
    room, _, _, current = await _regenerated_room(db_client, db_session)
    kept = await _kept(db_session, room)

    events = await _regenerate(db_client, room, _LLM("안 쓰일 응답", generation_error=error))

    assert "done" not in events
    assert (await _messages(db_session, room))[-1] == current
    assert await _kept(db_session, room) == kept
    assert await _previous_response_for(db_client, room) == str(current[0])


# ── 되돌리기 ─────────────────────────────────────────────────────────────────────────────


async def test_restoring_swaps_the_replaced_reply_back_in_and_restoring_again_swaps_back(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _, original, current = await _regenerated_room(db_client, db_session)
    before = await _messages(db_session, room)

    restored = await _restore(db_client, room, current[0], message_limit=2)

    assert restored.status_code == 200, restored.text
    body = restored.json()
    # 방 응답이고, 위로 불러 둔 깊이(`messageLimit`)만큼 싣는다.
    assert [message["id"] for message in body["messages"]] == [str(before[-2][0]), str(original[0])]
    assert body["hasMoreMessagesBefore"] is True
    assert body["previousResponseFor"] == str(original[0])
    # 원래 id·시각 그대로 같은 자리에 돌아온다.
    assert await _messages(db_session, room) == [*before[:-1], original]
    assert await _kept(db_session, room) == (original[0], current[0], current[3], "어긴 응답", None)

    swapped_back = await _restore(db_client, room, original[0])

    assert swapped_back.status_code == 200, swapped_back.text
    assert swapped_back.json()["previousResponseFor"] == str(current[0])
    assert await _messages(db_session, room) == before
    assert await _kept(db_session, room) == (current[0], original[0], original[3], "지킨 응답", None)


async def test_the_same_restore_sent_twice_is_refused_the_second_time_and_keeps_the_swap(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _, original, current = await _regenerated_room(db_client, db_session)
    assert (await _restore(db_client, room, current[0])).status_code == 200
    after_first = (await _messages(db_session, room), await _kept(db_session, room))

    second = await _restore(db_client, room, current[0])

    assert second.status_code == 409
    assert second.json() == _UNAVAILABLE
    assert (await _messages(db_session, room), await _kept(db_session, room)) == after_first
    # 보관 행은 지금 응답을 가리킨 채 남는다 — 다시 맞바꿀 수 있다.
    assert await _previous_response_for(db_client, room) == str(original[0])


async def test_restoring_without_a_kept_reply_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _ = await _story_room(db_session, db_client)
    await _send(db_client, room, _LLM("지킨 응답", ["a1"]))
    last = (await _messages(db_session, room))[-1]

    response = await _restore(db_client, room, last[0])

    assert response.status_code == 409
    assert response.json() == _UNAVAILABLE
    assert (await _messages(db_session, room))[-1] == last


async def test_restoring_a_reply_that_is_not_the_one_kept_for_is_refused_and_keeps_the_kept_reply(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _, _, current = await _regenerated_room(db_client, db_session)
    kept = await _kept(db_session, room)
    opening = (await _messages(db_session, room))[0]

    response = await _restore(db_client, room, opening[0])

    assert response.status_code == 409
    assert response.json() == _UNAVAILABLE
    assert await _kept(db_session, room) == kept
    assert (await _messages(db_session, room))[-1] == current


async def test_a_kept_reply_left_behind_by_a_change_the_image_did_not_clear_is_refused_and_removed(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """보관 테이블을 모르는 옛 이미지가 대화를 바꾸면(여기서는 메시지를 하나 더 넣는다) 보관 행이 남는다. 그 행이 가리키는 응답이
    더는 마지막이 아니므로 되돌리지 않고, 그 요청에서 낡은 행을 지운다."""
    room, _, _, current = await _regenerated_room(db_client, db_session)
    db_session.add(
        ChatMessage(
            chat_room_id=room.room_id,
            role=ChatMessageRole.USER,
            content="옛 이미지가 넣은 말",
            created_at=current[3] + timedelta(seconds=1),
        )
    )
    await db_session.commit()

    response = await _restore(db_client, room, current[0])

    assert response.status_code == 409
    assert response.json() == _UNAVAILABLE
    assert await _kept(db_session, room) is None
    assert [message[2] for message in await _messages(db_session, room)][-2:] == ["어긴 응답", "옛 이미지가 넣은 말"]


async def test_restoring_is_refused_while_a_turn_holds_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _, _, current = await _regenerated_room(db_client, db_session)
    kept = await _kept(db_session, room)
    await redis_client.set(f"chat_room:turn_lock:{room.room_id}", "다른 턴", px=60_000)

    response = await _restore(db_client, room, current[0])

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "CHAT_TURN_IN_PROGRESS"}}
    assert (await _messages(db_session, room))[-1] == current
    assert await _kept(db_session, room) == kept
    assert await redis_client.get(f"chat_room:turn_lock:{room.room_id}") == "다른 턴"


async def test_restoring_works_in_a_room_whose_content_is_restricted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _, original, current = await _regenerated_room(db_client, db_session)
    content_id = await db_session.scalar(sa.select(ChatRoom.content_id).where(ChatRoom.id == room.room_id))
    await db_session.execute(
        sa.update(Content).where(Content.id == content_id).values(moderation_status=ModerationStatus.RESTRICTED)
    )
    await db_session.commit()

    response = await _restore(db_client, room, current[0])

    assert response.status_code == 200, response.text
    assert (await _messages(db_session, room))[-1] == original


async def test_restoring_someone_elses_room_is_forbidden(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _, _, current = await _regenerated_room(db_client, db_session)
    stranger = _make_user()
    db_session.add(stranger)
    await db_session.commit()
    await _login_as(db_client, stranger.id)

    response = await _restore(db_client, room, current[0])

    assert response.status_code == 403
    assert (await _messages(db_session, room))[-1] == current


async def test_restoring_spends_nothing_and_writes_no_turn_record(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """클로버를 낼 수밖에 없는 사용자(무료분 0, 잔액 100, 오늘치 동의)로 보내기·재생성은 깎이고, 되돌리기는 잔액·원장·상한
    카운터·턴 기록이 그대로다. 폐기 기록에는 `undo` 하나가 더해진다."""
    user = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    user_id = user.id
    room = await _open_room(db_client, db_session, turns=0, user=user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    await _send(db_client, room, _LLM("첫 응답"))
    await _regenerate(db_client, room, _LLM("새 응답"))
    current = (await _messages(db_session, room))[-1]

    async def spending() -> tuple[object, ...]:
        db_session.expire_all()
        balance = await db_session.scalar(sa.select(User.clover_balance).where(User.id == user_id))
        ledger = await db_session.scalar(
            sa.select(sa.func.count()).select_from(CloverLedger).where(CloverLedger.user_id == user_id)
        )
        records = await db_session.scalar(
            sa.select(sa.func.count()).select_from(ChatTurn).where(ChatTurn.chat_room_id == room.room_id)
        )
        counters = {key: await redis_client.get(key) for key in sorted(await redis_client.keys("rate_limit:*"))}
        return balance, ledger, records, counters

    spent = await spending()
    assert spent[0] == 100 - 2 * clover.CHAT_TURN_COST

    response = await _restore(db_client, room, current[0])

    assert response.status_code == 200, response.text
    assert await spending() == spent
    discarded = (
        await db_session.execute(
            sa.select(DiscardedResponse.kind, DiscardedResponse.discarded_count)
            .where(DiscardedResponse.chat_room_id == room.room_id)
            .order_by(DiscardedResponse.kind)
        )
    ).all()
    assert [tuple(row) for row in discarded] == [("regenerate", 1), ("undo", 1)]


# ── 스탯 ─────────────────────────────────────────────────────────────────────────────────


async def test_restoring_brings_back_the_stats_the_restored_reply_left_and_restoring_again_swaps_them_back(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, stats, original, current = await _regenerated_room(db_client, db_session)
    assert await _stat_values(db_session, room, stats) == (71, 29)

    restored = await _restore(db_client, room, current[0])

    assert restored.status_code == 200
    assert await _stat_values(db_session, room, stats) == (78, 29)
    assert restored.json()["stats"] == {stats.trust: 78, stats.days: 29}

    assert (await _restore(db_client, room, original[0])).status_code == 200
    assert await _stat_values(db_session, room, stats) == (71, 29)


async def test_restoring_brings_back_the_counter_the_restored_turn_left(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """원 턴의 판정이 실패해 카운터가 구르지 않았고(30), 재생성의 재판정이 굴렸다(29). 되돌리면 카운터도 30 으로 돌아온다."""
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, room, _LLM("판정 실패한 응답", stat_error=True))
    await _regenerate(db_client, room, _LLM("지킨 응답", ["a1"]))
    assert await _stat_values(db_session, room, stats) == (78, 29)
    current = (await _messages(db_session, room))[-1]

    assert (await _restore(db_client, room, current[0])).status_code == 200

    assert await _stat_values(db_session, room, stats) == (73, 30)


async def test_restoring_leaves_a_stat_dropped_from_the_definitions_as_it_is(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """앞 테스트와 같은 방에서 카운터 정의가 사라졌으면(그 스탯이 없는 버전으로 옮겼다) 카운터 행은 쓰지 않는다."""
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, room, _LLM("판정 실패한 응답", stat_error=True))
    await _regenerate(db_client, room, _LLM("지킨 응답", ["a1"]))
    current = (await _messages(db_session, room))[-1]
    await db_session.execute(sa.delete(StatDef).where(StatDef.entity_id == uuid.UUID(stats.days)))
    await db_session.commit()

    assert (await _restore(db_client, room, current[0])).status_code == 200

    assert await _stat_values(db_session, room, stats) == (73, 29)


async def test_restoring_a_regeneration_that_kept_the_old_effect_leaves_the_stats_as_they_are(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, stats = await _story_room(db_session, db_client)
    await _send(db_client, room, _LLM("지킨 응답", ["a1"]))
    original = (await _messages(db_session, room))[-1]
    # 재판정이 실패해 옛 효과를 이어받은 재생성.
    await _regenerate(db_client, room, _LLM("새 응답", stat_error=True))
    current = (await _messages(db_session, room))[-1]
    assert await _stat_values(db_session, room, stats) == (78, 29)

    assert (await _restore(db_client, room, current[0])).status_code == 200

    assert await _stat_values(db_session, room, stats) == (78, 29)
    assert (await _messages(db_session, room))[-1] == original


async def _record_reached_an_ending(db_session: AsyncSession, room: Room, current: _Message) -> None:
    await db_session.execute(
        sa.update(ChatTurn).where(ChatTurn.assistant_message_id == current[0]).values(ending_entity_id=uuid.uuid4())
    )


async def _room_ended(db_session: AsyncSession, room: Room, _current: _Message) -> None:
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(ending_reached=True))


async def _later_turn_counted(db_session: AsyncSession, room: Room, _current: _Message) -> None:
    await db_session.execute(
        sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(turn_count=ChatRoom.turn_count + 1)
    )


async def _no_records(db_session: AsyncSession, room: Room, _current: _Message) -> None:
    await db_session.execute(sa.delete(ChatTurn).where(ChatTurn.chat_room_id == room.room_id))


_OUTSIDE = [
    pytest.param(_record_reached_an_ending, id="reply-record-reached-an-ending"),
    pytest.param(_room_ended, id="room-reached-an-ending"),
    pytest.param(_later_turn_counted, id="not-the-last-turn"),
    pytest.param(_no_records, id="no-turn-records"),
]


@pytest.mark.parametrize("change", _OUTSIDE)
async def test_restoring_outside_the_rejudgment_conditions_swaps_the_reply_but_not_the_stats(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    change: Callable[[AsyncSession, Room, _Message], Awaitable[None]],
) -> None:
    room, stats, original, current = await _regenerated_room(db_client, db_session)
    await change(db_session, room, current)
    await db_session.commit()
    ended = await db_session.scalar(sa.select(ChatRoom.ending_reached).where(ChatRoom.id == room.room_id))

    assert (await _restore(db_client, room, current[0])).status_code == 200

    assert await _stat_values(db_session, room, stats) == (71, 29)
    assert (await _messages(db_session, room))[-1] == original
    # 엔딩은 손대지 않는다.
    assert await db_session.scalar(sa.select(ChatRoom.ending_reached).where(ChatRoom.id == room.room_id)) == ended


# ── 요약·기억 ────────────────────────────────────────────────────────────────────────────


async def _plant_snapshot_at(db_session: AsyncSession, room: Room, message: _Message, text: str) -> uuid.UUID:
    snapshot = ChatRoomMemorySnapshot(
        chat_room_id=room.room_id,
        cursor_created_at=message[3],
        cursor_message_id=message[0],
        summary_text=text,
        source="auto",
    )
    db_session.add(snapshot)
    await db_session.flush()
    db_session.add(_make_memory_episode(room.room_id, snapshot.id))
    await db_session.commit()
    return snapshot.id


async def _memory(db_session: AsyncSession, room: Room) -> tuple[list[str], int, int, bool]:
    """(남은 요약 글, 장면 기억 수, 기억 버전, 되감김 표시 유무)."""
    db_session.expire_all()
    texts = (
        await db_session.scalars(
            sa.select(ChatRoomMemorySnapshot.summary_text)
            .where(ChatRoomMemorySnapshot.chat_room_id == room.room_id)
            .order_by(ChatRoomMemorySnapshot.cursor_created_at)
        )
    ).all()
    episodes = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMemoryEpisode).where(ChatMemoryEpisode.chat_room_id == room.room_id)
    )
    version, rolled_back_at = (
        await db_session.execute(
            sa.select(ChatRoom.memory_version, ChatRoom.memory_rolled_back_at).where(ChatRoom.id == room.room_id)
        )
    ).one()
    return list(texts), episodes or 0, version, rolled_back_at is not None


async def test_restoring_rewinds_the_summary_that_covered_either_reply(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """재생성 뒤 접기가 새 응답까지 덮었으면 되돌릴 때 그 요약과 장면 기억이 사라지고, 앞 턴만 덮은 요약은 남는다. 되살린
    응답(더 앞선 키)까지 덮는 요약도 다시 맞바꿀 때 사라진다 — 두 응답 중 앞선 키부터 되감는다."""
    room, _ = await _story_room(db_session, db_client, turns=1)
    await _send(db_client, room, _LLM("지킨 응답", ["a1"]))
    await _regenerate(db_client, room, _LLM("어긴 응답", ["a2"]))
    messages = await _messages(db_session, room)
    current = messages[-1]
    await _plant_snapshot_at(db_session, room, messages[2], "첫 턴 요약")
    await _plant_snapshot_at(db_session, room, current, "새 응답까지 요약")
    _, _, version, _ = await _memory(db_session, room)

    assert (await _restore(db_client, room, current[0])).status_code == 200

    assert await _memory(db_session, room) == (["첫 턴 요약"], 1, version + 1, True)

    restored = (await _messages(db_session, room))[-1]
    await _plant_snapshot_at(db_session, room, restored, "되살린 응답까지 요약")

    assert (await _restore(db_client, room, restored[0])).status_code == 200

    assert await _memory(db_session, room) == (["첫 턴 요약"], 1, version + 2, True)


# ── 턴 기록 ──────────────────────────────────────────────────────────────────────────────


async def test_regenerating_after_a_restore_rejudges_from_the_restored_replys_record(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, stats, original, current = await _regenerated_room(db_client, db_session)
    assert (await _restore(db_client, room, current[0])).status_code == 200
    record = await _record(db_session, original[0])
    assert record is not None and record.kind == "send"

    await _regenerate(db_client, room, _LLM("아무 일 없는 응답", []))

    latest = (await _messages(db_session, room))[-1]
    # 되살린 응답의 기록(73→78, 30→29)으로 되돌린 뒤 다시 판정했다.
    assert await _stat_values(db_session, room, stats) == (73, 29)
    record = await _record(db_session, latest[0])
    assert record is not None
    assert (record.kind, record.turn_number, record.stat_changes) == ("regenerate", 1, {stats.days: [30, 29]})
    assert await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatTurn).where(ChatTurn.chat_room_id == room.room_id)
    ) == 3
    kept = await _kept(db_session, room)
    assert kept is not None and kept[1] == original[0]


# ── 무효화 ───────────────────────────────────────────────────────────────────────────────


async def _send_that_fails(client: httpx.AsyncClient, room: Room, _messages_now: list[_Message]) -> None:
    fake = _LLM("", generation_error=LLMClientError("생성 실패"))
    assert "done" not in await _stream(client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "또"}, fake)


async def _edit_that_fails(client: httpx.AsyncClient, room: Room, messages_now: list[_Message]) -> None:
    user_message = messages_now[-2]
    fake = _LLM("", generation_error=LLMClientError("생성 실패"))
    path = f"/chat-rooms/{room.room_id}/messages/{user_message[0]}"
    assert "done" not in await _stream(client, "PATCH", path, {"content": "고친 말"}, fake)


async def _delete_the_opening(client: httpx.AsyncClient, room: Room, messages_now: list[_Message]) -> None:
    response = await client.delete(f"/chat-rooms/{room.room_id}/messages/{messages_now[0][0]}")
    assert response.status_code == 200, response.text


async def _reset(client: httpx.AsyncClient, room: Room, _messages_now: list[_Message]) -> None:
    response = await client.post(f"/chat-rooms/{room.room_id}/reset")
    assert response.status_code == 200, response.text


_CLEARING = [
    pytest.param(_send_that_fails, id="send"),
    pytest.param(_edit_that_fails, id="edit"),
    pytest.param(_delete_the_opening, id="delete-message"),
    pytest.param(_reset, id="reset"),
]


@pytest.mark.parametrize("change", _CLEARING)
async def test_changing_the_conversation_removes_the_kept_reply(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    change: Callable[[httpx.AsyncClient, Room, list[_Message]], Awaitable[None]],
) -> None:
    """보내기·수정은 생성이 실패해도 지운다 — 사용자 메시지·절단과 같은 커밋(생성 전)이다. 메시지 삭제는 마지막이 아닌
    메시지를 지워도 지운다."""
    room, _, _, _ = await _regenerated_room(db_client, db_session)
    assert await _kept(db_session, room) is not None

    await change(db_client, room, await _messages(db_session, room))

    assert await _kept(db_session, room) is None
    assert await _previous_response_for(db_client, room) is None


async def test_deleting_the_room_removes_the_kept_reply_through_the_room_fk(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _, _, _ = await _regenerated_room(db_client, db_session)
    assert await _kept(db_session, room) is not None

    response = await db_client.delete(f"/chat-rooms/{room.room_id}")

    assert response.status_code == 204, response.text
    assert await _kept(db_session, room) is None


async def test_withdrawal_removes_the_kept_reply_through_the_room_fk(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _, _, _ = await _regenerated_room(db_client, db_session)
    assert await _kept(db_session, room) is not None
    user = await db_session.get(User, room.user_id)
    assert user is not None

    async def keep(_key: str) -> None:
        return None

    await erase_account(db_session, user, delete_storage_object=keep)

    assert await _kept(db_session, room) is None
    assert await db_session.scalar(sa.select(ChatRoom.id).where(ChatRoom.id == room.room_id)) is None


async def test_an_image_that_does_not_know_the_table_can_still_delete_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """배포 겹침 동안의 옛 이미지는 이 테이블을 모르고 방 삭제의 자식 목록을 아래 순서로 지운 뒤 방을 지운다. 보관 행이 있어도
    FK 위반 없이 끝난다."""
    room, _, _, _ = await _regenerated_room(db_client, db_session)
    assert await _kept(db_session, room) is not None
    room_ids = [room.room_id]

    await db_session.execute(
        sa.update(ChatRoom).where(ChatRoom.id.in_(room_ids)).values(memory_version=ChatRoom.memory_version + 1)
    )
    await db_session.execute(
        sa.delete(ChatRoomMemorySnapshot).where(ChatRoomMemorySnapshot.chat_room_id.in_(room_ids))
    )
    await db_session.execute(sa.delete(ChatRoomStat).where(ChatRoomStat.chat_room_id.in_(room_ids)))
    await db_session.execute(sa.delete(ChatTurn).where(ChatTurn.chat_room_id.in_(room_ids)))
    await db_session.execute(sa.delete(ChatMessage).where(ChatMessage.chat_room_id.in_(room_ids)))
    await db_session.execute(sa.delete(ChatRoom).where(ChatRoom.id.in_(room_ids)))
    await db_session.commit()

    assert await _kept(db_session, room) is None
