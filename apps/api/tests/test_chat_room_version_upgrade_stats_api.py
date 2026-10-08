"""방이 새 발행 버전으로 옮겨 갈 때(사용자의 최신 버전 고정, 제한 해제·이의 수용의 자동 승격) 스탯 행.

새 버전에 생긴 스탯의 행이 없으면 그 스탯을 바꾸는 턴(카운터면 매 턴)이 행을 찾다 예외로 끊긴다. 응답은 토큰에서
멈추고 AI 메시지·턴 수·스탯이 커밋되지 않는다.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, StatRuleJudgmentResult
from api.db.models import (
    ChatRoom,
    ChatRoomStat,
    Content,
    ContentVersion,
    Ending,
    EndingRule,
    EndingRuleOperator,
    StartingSetup,
    StatDef,
    StatRule,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.llm.client import LLMCallContext, LLMClient
from api.moderation.router import upgrade_content_chat_rooms_to_latest_version
from factories import (
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_asset,
    _make_published_story,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
)


class _QueueLLM(LLMClient):
    def __init__(self, structured_results: list[Any]) -> None:
        self._results = list(structured_results)
        self.call_sites: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.call_sites.append(usage.call_site)
        yield "안녕"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.call_sites.append(usage.call_site)
        return self._results.pop(0)


async def _setup(db_session: AsyncSession, version_id: uuid.UUID, entity_id: uuid.UUID) -> StartingSetup:
    setup = StartingSetup(
        entity_id=entity_id, content_version_id=version_id, name="첫 만남", prologue="프롤로그", order=1
    )
    db_session.add(setup)
    await db_session.flush()
    return setup


def _stat(setup: StartingSetup, entity_id: uuid.UUID, *, order: int, per_turn_delta: int | None = None) -> StatDef:
    return StatDef(
        id=uuid.uuid4(),
        entity_id=entity_id,
        starting_setup_id=setup.id,
        name=f"스탯{order}",
        icon="heart",
        color="#ff0000",
        min_value=0,
        max_value=100,
        initial_value=50,
        unit=None,
        description="스탯",
        order=order,
        per_turn_delta=per_turn_delta,
    )


def _rules(*stats: StatDef) -> list[StatRule]:
    """판정 스탯마다 규칙 하나(폭 +20). 규칙이 있어야 스탯 판정이 불린다. 실린 순서대로 a1, b1 … 이다."""
    return [
        StatRule(entity_id=uuid.uuid4(), stat_def_id=stat.id, condition=f"{stat.name} 조건", delta=20, order=0)
        for stat in stats
        if stat.per_turn_delta is None
    ]


async def _publish_v2(db_session: AsyncSession, content: Content) -> ContentVersion:
    version = ContentVersion(
        content_id=content.id, version_number=2, published_at=datetime.now(UTC), detail_description="설명 v2"
    )
    db_session.add(version)
    await db_session.flush()
    thumbnail = await _make_asset(db_session, owner_user_id=content.creator_user_id)
    db_session.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name="스토리 v2",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text="세계관 설정 v2",
        )
    )
    content.current_published_version_id = version.id
    await db_session.flush()
    return version


class _Upgraded:
    def __init__(self, room_id: uuid.UUID, kept: uuid.UUID, added: uuid.UUID, dropped: uuid.UUID) -> None:
        self.room_id = room_id
        self.kept = kept
        self.added = added
        self.dropped = dropped


async def _upgraded_room(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    *,
    via: str,
    added_delta: int | None = None,
    rule_on_added: bool = False,
) -> tuple[_Upgraded, httpx.Response | None]:
    """v1(유지 스탯·빠질 스탯)으로 방을 만들고 유지 스탯을 30 으로 플레이해 둔 뒤, v2(유지 스탯·새 스탯)로 옮긴다.
    `via` 는 "pin"(사용자의 최신 버전 고정) 또는 "auto"(제한 해제·이의 수용이 부르는 일괄 승격)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    assert content.current_published_version_id is not None
    setup_entity, kept, added, dropped = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    v1_setup = await _setup(db_session, content.current_published_version_id, setup_entity)
    db_session.add_all([_stat(v1_setup, kept, order=1), _stat(v1_setup, dropped, order=2)])
    await db_session.commit()
    await _login_as(db_client, user.id)
    created = await db_client.post(
        "/chat-rooms",
        json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(v1_setup.id)},
    )
    assert created.status_code == 201, created.text
    room_id = uuid.UUID(created.json()["id"])
    kept_row = await db_session.get(ChatRoomStat, (room_id, kept))
    assert kept_row is not None
    kept_row.current_value = Decimal(30)

    v2 = await _publish_v2(db_session, content)
    v2_setup = await _setup(db_session, v2.id, setup_entity)
    v2_stats = [_stat(v2_setup, kept, order=1), _stat(v2_setup, added, order=2, per_turn_delta=added_delta)]
    db_session.add_all(v2_stats)
    await db_session.flush()
    db_session.add_all(_rules(*v2_stats))
    if rule_on_added:
        ending = Ending(
            entity_id=uuid.uuid4(),
            starting_setup_id=v2_setup.id,
            name="엔딩",
            turn_count_gate=1,
            judgment_prompt="떠났는가?",
            epilogue="끝.",
            order=1,
        )
        db_session.add(ending)
        await db_session.flush()
        db_session.add(
            EndingRule(
                entity_id=uuid.uuid4(),
                ending_id=ending.id,
                stat_def_entity_id=added,
                operator=EndingRuleOperator.GTE,
                threshold=40,
                order=1,
            )
        )
    await db_session.commit()

    pin_response: httpx.Response | None = None
    if via == "pin":
        pin_response = await db_client.post(f"/chat-rooms/{room_id}/pin-latest-version")
        assert pin_response.status_code == 200, pin_response.text
    else:
        await upgrade_content_chat_rooms_to_latest_version(db_session, content)
        await db_session.commit()
    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    await db_session.refresh(room)
    assert room.content_version_id == v2.id
    return _Upgraded(room_id, kept, added, dropped), pin_response


async def _stat_values(db_session: AsyncSession, room_id: uuid.UUID) -> dict[uuid.UUID, float]:
    rows = (await db_session.scalars(select(ChatRoomStat).where(ChatRoomStat.chat_room_id == room_id))).all()
    return {row.stat_entity_id: float(row.current_value) for row in rows}


async def _send(db_client: httpx.AsyncClient, room_id: uuid.UUID, fake: _QueueLLM) -> list[str]:
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200
    return [event["type"] for event in _parse_sse_events(resp.text)]


@pytest.mark.parametrize("via", [pytest.param("pin", id="pin"), pytest.param("auto", id="auto-upgrade")])
async def test_upgrade_seeds_stats_added_in_new_version_and_keeps_existing_values(
    db_client: httpx.AsyncClient, db_session: AsyncSession, via: str
) -> None:
    """새 스탯은 시작값으로 채우고 플레이한 값은 덮지 않는다. 새 버전에서 빠진 스탯의 행은 지우지 않는다 —
    턴은 현재 버전의 스탯 정의만 읽으므로 남은 행은 쓰이지 않고, 승격은 초기화가 아니라서 지금까지처럼 둔다."""
    upgraded, pin_response = await _upgraded_room(db_client, db_session, via=via)

    expected = {upgraded.kept: 30.0, upgraded.added: 50.0, upgraded.dropped: 50.0}
    assert await _stat_values(db_session, upgraded.room_id) == expected
    if pin_response is not None:
        # 화면의 스탯 패널은 이 응답으로 그린다 — 새 스탯이 바로 보여야 한다.
        assert pin_response.json()["stats"] == {str(stat_id): value for stat_id, value in expected.items()}


@pytest.mark.parametrize(
    ("via", "added_delta", "judged", "expected"),
    [
        pytest.param("pin", None, True, 70.0, id="pin-judged-stat"),
        pytest.param("pin", -1, False, 49.0, id="pin-counter-stat"),
        pytest.param("auto", -1, False, 49.0, id="auto-upgrade-counter-stat"),
    ],
)
async def test_turn_after_upgrade_updates_stat_added_in_new_version(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    via: str,
    added_delta: int | None,
    judged: bool,
    expected: float,
) -> None:
    upgraded, _ = await _upgraded_room(db_client, db_session, via=via, added_delta=added_delta)
    # 판정 스탯이면 새 스탯의 규칙(b1, +20)을 발동시킨다. 카운터면 판정할 것은 유지 스탯의 규칙뿐이고 발동시키지 않는다.
    fired = ["b1"] if judged else []

    events = await _send(db_client, upgraded.room_id, _QueueLLM([StatRuleJudgmentResult(fired_rule_ids=fired)]))

    assert events == ["token", "statChange", "done"]
    values = await _stat_values(db_session, upgraded.room_id)
    assert (values[upgraded.added], values[upgraded.kept]) == (expected, 30.0)
    room = await db_session.get(ChatRoom, upgraded.room_id)
    assert room is not None
    await db_session.refresh(room)
    assert room.turn_count == 1


async def _drop_added_row(db_session: AsyncSession, upgraded: _Upgraded) -> None:
    """이 수정 전에 옮겨 간 방처럼 새 스탯의 행이 없는 상태를 만든다."""
    await db_session.execute(
        delete(ChatRoomStat).where(
            ChatRoomStat.chat_room_id == upgraded.room_id, ChatRoomStat.stat_entity_id == upgraded.added
        )
    )
    await db_session.commit()


async def test_turn_creates_missing_row_for_counter_stat_of_room_upgraded_without_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    upgraded, _ = await _upgraded_room(db_client, db_session, via="pin", added_delta=-1)
    await _drop_added_row(db_session, upgraded)

    events = await _send(db_client, upgraded.room_id, _QueueLLM([StatRuleJudgmentResult(fired_rule_ids=[])]))

    assert events == ["token", "statChange", "done"]
    assert (await _stat_values(db_session, upgraded.room_id))[upgraded.added] == 49.0


async def test_ending_rule_reads_missing_stat_row_as_its_initial_value(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """행이 없는 새 스탯은 시작값(50)으로 본다 — 승격이 채웠을 값과 같다. 그래서 `>= 40` 규칙이 참이 되어 판정한다."""
    upgraded, _ = await _upgraded_room(db_client, db_session, via="pin", rule_on_added=True)
    await _drop_added_row(db_session, upgraded)
    fake = _QueueLLM([StatRuleJudgmentResult(fired_rule_ids=[]), EndingJudgmentResult(triggered=True)])

    events = await _send(db_client, upgraded.room_id, fake)

    assert events == ["token", "endingReached", "done"]
    assert fake.call_sites == ["chat_generate", "chat_stat_judgment", "chat_ending_judgment"]
