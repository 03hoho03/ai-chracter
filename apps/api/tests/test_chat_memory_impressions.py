"""요약 접기 몇 번마다 방 하나에 인상 한 행을 쌓는다(저장만 — 생성에 싣지 않는다).

- 언제: 스위치(`memory_impressions_write`)가 켜져 있으면 턴 뒤 접기·두 추출 예약 **뒤에** 따로 예약한다. 꺼져 있으면 예약하지
  않는다(턴의 호출·트랜잭션이 스위치가 생기기 전과 같다). 작업은 방의 스냅샷 수가 `memory_impression_every_n_folds` 의 배수이고,
  가장 새 스냅샷에 인상이 아직 없고, 묶음(가장 새 것까지 N 개) 스냅샷의 장면·사실 추출이 모두 끝났을 때만 모델을 부른다. 그
  턴의 레인과 글쓰기 모델이 기억 사용 범위 밖이면 아무것도 하지 않는다.
- 입력: 묶음 스냅샷의 장면·사실 행 전부다 — 아는 사람(`known_by`)이 정해진 행도 같은 줄 모양으로 들어간다. 인상 행의 근거 id
  는 입력에 쓴 행 id 전부라, 인상을 어딘가에 싣는 쪽이 근거 행 단위로 비밀을 거를 수 있다. 요약 글·원문 창은 싣지 않는다.
- 쓰기: 마지막 트랜잭션은 가장 새 스냅샷을 `FOR KEY SHARE` 로 잠근 뒤 방의 잊기 세대를 다시 읽고, 입력을 읽을 때와 다르면 결과를
  버린다. 잊게 하기(장면·사실 모두)는 그 방의 인상을 전부 지우고 잊기 세대를 올린다.

진짜 두 세션의 경합(잊기가 생성 커밋을 기다리는가)은 `test_chat_memory_rewind.py` 의 커밋되는 독립 커넥션 절에 있다. 운영 문안이
바뀌어도 깨지지 않게 테스트는 세트의 인상 문안을 합성 섹션으로 바꿔 넘긴다.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_impressions
from api.chat.memory_forget import forget_episode, forget_fact_key
from api.chat.memory_impressions import generate_pending_impression
from api.chat.memory_rewind import rewind_memory
from api.chat.prompt_builder import (
    MemoryEpisodeResult,
    MemoryFactResult,
    MemoryImpressionResult,
    MemorySummaryResult,
    PromptLane,
    StatRuleJudgmentResult,
    load_active_prompt_set,
)
from api.chat.room_deletion import delete_chat_rooms
from api.core.config import settings
from api.db.models import ChatMemoryImpression, ChatMemoryImpressionAttempt, ChatRoom, ChatRoomMemorySnapshot
from api.db.models.chat import IMPRESSION_TEXT_MAX
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, collect_usage
from factories import (
    IMPRESSION_SYNTHETIC_INSTRUCTION,
    Room,
    _clear_llm_override,
    _impression_sections,
    _make_memory_episode,
    _make_memory_extraction,
    _make_memory_fact,
    _make_memory_fact_extraction,
    _open_room,
    _open_transaction_probe,
    _override_llm_client,
    _parse_sse_events,
    _plant_snapshot,
)

ImpressionOutcome = MemoryImpressionResult | Exception | Callable[[], Awaitable[MemoryImpressionResult]]


class ImpressionLLMClient(LLMClient):
    """생성은 고정 응답, 요약은 고정 본문, 스탯 판정은 변화 없음, 두 추출은 빈 결과. 인상 호출에는 `outcomes` 를 차례로 준다
    (결과는 그대로, 예외는 raise, 콜러블은 불러서 그 결과를 — 호출 도중의 경합을 흉내 낸다). 다 쓰면 고정 인상이다.
    `open_sessions` 가 있으면 인상 호출 순간 열린 루트 트랜잭션 수를 적는다. `usage_metadata` 가 있으면 그 사용량을 호출의
    `usage_sink` 에 더한다(공급자 구현이 하는 일과 같다 — 결과를 내기 전, 예외를 내는 호출도)."""

    def __init__(
        self,
        *outcomes: ImpressionOutcome,
        open_sessions: set[int] | None = None,
        usage_metadata: object | None = None,
    ) -> None:
        self.outcomes = list(outcomes)
        self.open_sessions = open_sessions
        self.usage_metadata = usage_metadata
        self.prompts: list[str] = []
        self.usages: list[LLMCallContext] = []
        self.open_at_call: list[int] = []

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
            return StatRuleJudgmentResult(fired_rule_ids=[])
        if response_schema is MemorySummaryResult:
            return MemorySummaryResult(summary="[SUMMARY] 요약")
        if response_schema is MemoryEpisodeResult:
            return MemoryEpisodeResult(episodes=[])
        if response_schema is MemoryFactResult:
            return MemoryFactResult(facts=[])
        assert response_schema is MemoryImpressionResult, response_schema
        self.prompts.append(prompt)
        self.usages.append(usage)
        if self.open_sessions is not None:
            self.open_at_call.append(len(self.open_sessions))
        if self.usage_metadata is not None:
            collect_usage(usage, "claude-haiku-5-5", self.usage_metadata)
        outcome = (
            self.outcomes.pop(0) if self.outcomes else MemoryImpressionResult(impression="  서로를 믿기 시작했다.  ")
        )
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return await outcome()
        return outcome


def _savepoint_factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _kwargs(
    db_session: AsyncSession, room: Room, *, lane: PromptLane = "character", writing_model: str = "opus"
) -> dict[str, Any]:
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane)
    return {
        "room_id": room.room_id,
        "user_id": room.user_id,
        "prompt_set": prompt_set,
        "sections": _impression_sections(prompt_set, sections),
        "is_story_chat": lane == "story",
        "writing_model": writing_model,
    }


async def _generate(db_session: AsyncSession, room: Room, llm: LLMClient, **overrides: Any) -> None:
    kwargs = {**await _kwargs(db_session, room), **overrides}
    await generate_pending_impression(_savepoint_factory(db_session), llm, **kwargs)


async def _snapshot_id(db_session: AsyncSession, room: Room, turn: int) -> uuid.UUID:
    snapshot_id = await db_session.scalar(
        sa.select(ChatRoomMemorySnapshot.id).where(
            ChatRoomMemorySnapshot.chat_room_id == room.room_id,
            ChatRoomMemorySnapshot.cursor_message_id == room.turns[turn][1].id,
        )
    )
    assert snapshot_id is not None
    return snapshot_id


async def _plant(
    db_session: AsyncSession, room: Room, turn: int, *, episodes: bool = True, facts: bool = True
) -> uuid.UUID:
    """턴 `turn` 의 응답을 커서로 둔 스냅샷을 심는다. `episodes`·`facts` 면 그 추출이 끝난 기록도 함께."""
    await _plant_snapshot(db_session, room, turn=turn, text=f"[SUMMARY-S{turn}]")
    snapshot_id = await _snapshot_id(db_session, room, turn)
    if episodes:
        db_session.add(_make_memory_extraction(room.room_id, snapshot_id))
    if facts:
        db_session.add(_make_memory_fact_extraction(room.room_id, snapshot_id))
    await db_session.commit()
    return snapshot_id


async def _three_part_room(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[Room, list[uuid.UUID]]:
    """30턴 방. 턴 10·20·30 스냅샷이 있고 두 추출이 모두 끝났다(기본 N = 3 의 묶음 하나)."""
    room = await _open_room(db_client, db_session, turns=30)
    snapshots = [await _plant(db_session, room, turn) for turn in (10, 20, 30)]
    return room, snapshots


async def _scene(db_session: AsyncSession, room: Room, snapshot_id: uuid.UUID, **overrides: Any) -> uuid.UUID:
    row = _make_memory_episode(room.room_id, snapshot_id, **overrides)
    db_session.add(row)
    await db_session.commit()
    return row.id


async def _fact(db_session: AsyncSession, room: Room, snapshot_id: uuid.UUID, **overrides: Any) -> uuid.UUID:
    row = _make_memory_fact(room.room_id, snapshot_id, **overrides)
    db_session.add(row)
    await db_session.commit()
    return row.id


async def _impressions(db_session: AsyncSession, room: Room) -> list[Any]:
    return list(
        (
            await db_session.execute(
                sa.select(
                    ChatMemoryImpression.chat_room_id,
                    ChatMemoryImpression.snapshot_id,
                    ChatMemoryImpression.first_cursor_created_at,
                    ChatMemoryImpression.first_cursor_message_id,
                    ChatMemoryImpression.text,
                    ChatMemoryImpression.episode_ids,
                    ChatMemoryImpression.fact_ids,
                ).where(ChatMemoryImpression.chat_room_id == room.room_id)
            )
        ).all()
    )


async def _attempts(db_session: AsyncSession, room: Room) -> list[Any]:
    """방의 인상 시도 기록 — (스냅샷, 상태, 시도 수, 끝난 시각이 있는가)."""
    attempt = ChatMemoryImpressionAttempt
    return list(
        (
            await db_session.execute(
                sa.select(
                    attempt.snapshot_id,
                    attempt.status,
                    attempt.attempts,
                    attempt.finished_at.is_not(None).label("finished"),
                ).where(attempt.chat_room_id == room.room_id)
            )
        ).all()
    )


async def _generation(db_session: AsyncSession, room: Room) -> int:
    value = await db_session.scalar(sa.select(ChatRoom.memory_forget_generation).where(ChatRoom.id == room.room_id))
    assert value is not None
    return value


def _capture_failures(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    captured: list[str] = []
    monkeypatch.setattr(
        memory_impressions, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    return captured


# --- 예약 ---------------------------------------------------------------------------------


async def _send(db_client: httpx.AsyncClient, room: Room, fake: LLMClient) -> list[str]:
    _override_llm_client(fake)
    try:
        response = await db_client.post(f"/chat-rooms/{room.room_id}/messages", json={"content": "새 메시지"})
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    return [event["type"] for event in _parse_sse_events(response.text)]


def _record_scheduling(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    scheduled: list[str] = []
    original_add_task = BackgroundTasks.add_task

    def _recording_add_task(self: BackgroundTasks, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        scheduled.append(func.__name__)
        original_add_task(self, func, *args, **kwargs)

    monkeypatch.setattr(BackgroundTasks, "add_task", _recording_add_task)
    return scheduled


async def test_impression_is_not_scheduled_when_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """두 추출이 켜져 있어도 인상 스위치가 꺼져 있으면 예약이 두 추출에서 끝난다 — 인상 호출도 인상 행도 없다."""
    assert settings.memory_impressions_write is False
    monkeypatch.setattr(settings, "memory_episodes_extract", True)
    monkeypatch.setattr(settings, "memory_facts_extract", True)
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29)
    fake = ImpressionLLMClient()

    assert (await _send(db_client, room, fake))[-1] == "done"

    assert scheduled == ["fold_memory", "extract_pending_episode", "extract_pending_facts"]
    assert fake.prompts == []
    assert await _impressions(db_session, room) == []
    assert await _attempts(db_session, room) == []


async def test_impression_is_scheduled_after_both_extractions_and_skips_a_room_outside_the_memory_scope(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """켜져 있으면 두 추출 뒤에 예약된다. 이 방은 기본 모델(Gemini)로 쓰는 방이라 기억 사용 범위 밖이고, 그래서 접기와 두 추출이
    한 묶음(N = 1)을 끝냈어도 인상을 부르지 않는다."""
    monkeypatch.setattr(settings, "memory_episodes_extract", True)
    monkeypatch.setattr(settings, "memory_facts_extract", True)
    monkeypatch.setattr(settings, "memory_impressions_write", True)
    monkeypatch.setattr(settings, "memory_impression_every_n_folds", 1)
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29)
    fake = ImpressionLLMClient()

    assert (await _send(db_client, room, fake))[-1] == "done"

    assert scheduled == [
        "fold_memory",
        "extract_pending_episode",
        "extract_pending_facts",
        "generate_pending_impression",
    ]
    assert fake.prompts == []
    assert await _impressions(db_session, room) == []


# --- 언제 만드나 --------------------------------------------------------------------------------


async def test_a_due_group_becomes_one_impression_built_from_every_scene_and_fact_row_secret_or_not(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """묶음 세 스냅샷의 장면·사실 행이 아는 사람이 정해졌든 아니든 전부 입력이 된다 — 장면 추출이 그 장면에 있던 인물을 거의 늘
    아는 사람으로 적어서, 비밀 행을 빼면 장면 대부분이 빠지고 인상이 사실 줄에만 기댄다. 비밀 행도 공개 행과 같은 줄 모양이고
    (아는 사람 표기 없음), 근거 id 는 입력에 쓴 행 전부다. 행은 가장 새 스냅샷에 걸리고 첫 커서는 가장 오래된 스냅샷의 것이다.
    글은 앞뒤 공백을 걷는다. 모델을 기다리는 동안 커넥션을 쥐지 않는다."""
    room, (first, second, third) = await _three_part_room(db_client, db_session)
    public_scene = await _scene(db_session, room, first, title="첫 장면", detail="정류장에서 우산을 나눠 썼다.")
    secret_scene = await _scene(
        db_session, room, second, title="[비밀 장면]", detail="[비밀 장면 내용]", known_by=["지아"]
    )
    later_scene = await _scene(db_session, room, third, title="둘째 장면", detail="빵집 앞에서 다시 만났다.")
    public_fact = await _fact(db_session, room, second)
    secret_fact = await _fact(
        db_session,
        room,
        third,
        kind="fact",
        subject="지아",
        object=None,
        attribute="[비밀 속성]",
        fact_key="fact|지아|[비밀 속성]",
        value="[비밀 값]",
        known_by=["지아", "민수"],
    )
    attribute_fact = await _fact(
        db_session,
        room,
        third,
        ordinal=1,
        kind="fact",
        subject="민수",
        object=None,
        attribute="직업",
        fact_key="fact|민수|직업",
        value="제빵사",
        truth_status="claimed",
    )

    kwargs = await _kwargs(db_session, room)
    # 셋업이 같은 세션에 남긴 트랜잭션을 닫아 기준값을 0 으로 만든다.
    await db_session.commit()
    with _open_transaction_probe() as open_sessions:
        fake = ImpressionLLMClient(open_sessions=open_sessions)
        await generate_pending_impression(_savepoint_factory(db_session), fake, **kwargs)

    assert fake.open_at_call == [0]
    assert (fake.usages[0].call_site, fake.usages[0].room_id, fake.usages[0].user_id) == (
        "chat_memory_impression",
        room.room_id,
        room.user_id,
    )
    assert fake.prompts == [
        f"{IMPRESSION_SYNTHETIC_INSTRUCTION}\n\n"
        "[장면]\n- 첫 장면: 정류장에서 우산을 나눠 썼다.\n- [비밀 장면]: [비밀 장면 내용]\n"
        "- 둘째 장면: 빵집 앞에서 다시 만났다.\n\n"
        "[사실]\n- 민수 → 지아: 소꿉친구 (confirmed)\n- 지아 / [비밀 속성]: [비밀 값] (confirmed)\n"
        "- 민수 / 직업: 제빵사 (claimed)"
    ]
    assert "SUMMARY" not in fake.prompts[0] and "[U" not in fake.prompts[0]
    oldest = room.turns[10][1]
    assert await _impressions(db_session, room) == [
        (
            room.room_id,
            third,
            oldest.created_at,
            oldest.id,
            "서로를 믿기 시작했다.",
            [str(public_scene), str(secret_scene), str(later_scene)],
            [str(public_fact), str(secret_fact), str(attribute_fact)],
        )
    ]


async def test_secret_rows_take_their_place_in_the_snapshot_cursor_and_ordinal_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """입력 순서는 아는 사람과 무관하게 스냅샷 커서 순, 그 안은 순번 순이다 — 비밀 행이 공개 행 사이 제자리에 끼고 앞이나 뒤로
    몰리지 않는다. 행 수·글자 수 상한은 없어서 비밀 행이 들어와도 공개 행이 밀려나지 않는다. 근거 id 도 같은 순서다. 심는 순서를
    입력 순서와 다르게 둬 삽입 순서로 우연히 맞는 경우를 가른다."""
    room, (first, second, third) = await _three_part_room(db_client, db_session)
    later_scene = await _scene(db_session, room, second, title="둘째 장면", detail="빵집.")
    secret_scene = await _scene(db_session, room, first, ordinal=1, title="[비밀]", detail="[비밀]", known_by=["지아"])
    first_scene = await _scene(db_session, room, first, title="첫 장면", detail="우산.")
    public_fact = await _fact(db_session, room, third, ordinal=1, value="이웃")
    secret_fact = await _fact(db_session, room, third, ordinal=0, value="[비밀 사이]", known_by=["민수"])
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake)

    assert fake.prompts == [
        f"{IMPRESSION_SYNTHETIC_INSTRUCTION}\n\n"
        "[장면]\n- 첫 장면: 우산.\n- [비밀]: [비밀]\n- 둘째 장면: 빵집.\n\n"
        "[사실]\n- 민수 → 지아: [비밀 사이] (confirmed)\n- 민수 → 지아: 이웃 (confirmed)"
    ]
    [row] = await _impressions(db_session, room)
    assert (row.episode_ids, row.fact_ids) == (
        [str(first_scene), str(secret_scene), str(later_scene)],
        [str(secret_fact), str(public_fact)],
    )


async def test_only_the_last_n_snapshots_are_read(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N = 2 이고 스냅샷이 넷이면 묶음은 셋째·넷째 스냅샷이다 — 앞 두 스냅샷의 행은 입력에 없다."""
    monkeypatch.setattr(settings, "memory_impression_every_n_folds", 2)
    room = await _open_room(db_client, db_session, turns=40)
    snapshots = [await _plant(db_session, room, turn) for turn in (10, 20, 30, 40)]
    await _scene(db_session, room, snapshots[1], title="이미 묶인 장면", detail="앞 묶음.")
    kept = await _scene(db_session, room, snapshots[2], title="이번 장면", detail="이번 묶음.")
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake)

    assert "이미 묶인 장면" not in fake.prompts[0] and "이번 장면" in fake.prompts[0]
    [row] = await _impressions(db_session, room)
    assert (row.snapshot_id, row.first_cursor_message_id) == (snapshots[3], room.turns[30][1].id)
    assert (row.episode_ids, row.fact_ids) == ([str(kept)], [])


@pytest.mark.parametrize("count", [2, 4], ids=["one-short", "one-past"])
async def test_nothing_runs_when_the_snapshot_count_is_not_a_multiple_of_n(
    db_client: httpx.AsyncClient, db_session: AsyncSession, count: int
) -> None:
    room = await _open_room(db_client, db_session, turns=40)
    for turn in (10, 20, 30, 40)[:count]:
        snapshot_id = await _plant(db_session, room, turn)
        await _scene(db_session, room, snapshot_id)
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake)

    assert fake.prompts == []
    assert await _impressions(db_session, room) == []


@pytest.mark.parametrize(
    ("episodes", "facts", "status"),
    [
        (False, True, None),
        (True, False, None),
        (True, True, "failed"),
        (True, True, "running"),
    ],
    ids=["scenes-not-extracted", "facts-not-extracted", "fact-extraction-failed", "scene-extraction-running"],
)
async def test_nothing_runs_until_both_extractions_of_every_snapshot_in_the_group_are_done(
    db_client: httpx.AsyncClient, db_session: AsyncSession, episodes: bool, facts: bool, status: str | None
) -> None:
    """묶음의 가운데 스냅샷 하나만 덜 끝났다. 반쪽 입력으로 인상을 만들지 않는다."""
    room = await _open_room(db_client, db_session, turns=30)
    first = await _plant(db_session, room, 10)
    await _plant_snapshot(db_session, room, turn=20, text="[SUMMARY-S20]")
    middle = await _snapshot_id(db_session, room, 20)
    if episodes:
        overrides: dict[str, Any] = {"status": status, "episode_count": None} if status == "running" else {}
        db_session.add(_make_memory_extraction(room.room_id, middle, **overrides))
    if facts:
        overrides = {"status": status, "fact_count": None} if status == "failed" else {}
        db_session.add(_make_memory_fact_extraction(room.room_id, middle, **overrides))
    await db_session.commit()
    await _plant(db_session, room, 30)
    await _scene(db_session, room, first)
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake)

    assert fake.prompts == []
    assert await _impressions(db_session, room) == []


async def test_nothing_runs_outside_the_memory_model_scope(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """범위 판정은 접기와 같이 세트의 레인과 그 턴의 글쓰기 모델로 한다 — 기본 범위(Opus 방)에서 Gemini 로 쓴 턴은 묶음이 차
    있어도 아무것도 하지 않는다."""
    room, (first, _, _) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake, writing_model="gemini")

    assert fake.prompts == []
    assert await _impressions(db_session, room) == []
    assert await _attempts(db_session, room) == []


async def test_a_group_that_already_has_its_impression_is_not_redone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, (first, _, _) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake)
    await _generate(db_session, room, fake)

    assert len(fake.prompts) == 1
    assert len(await _impressions(db_session, room)) == 1


async def test_a_group_whose_every_row_is_secret_still_becomes_an_impression(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """묶음의 행이 전부 아는 사람이 정해진 행이어도 입력이 비지 않으므로 모델을 부르고, 근거 id 가 그 행들이다."""
    room, (first, second, _) = await _three_part_room(db_client, db_session)
    scene = await _scene(db_session, room, first, known_by=["지아"])
    fact = await _fact(db_session, room, second, known_by=["민수"])
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake)

    assert len(fake.prompts) == 1
    [row] = await _impressions(db_session, room)
    assert (row.episode_ids, row.fact_ids) == ([str(scene)], [str(fact)])


async def test_nothing_is_called_when_the_group_has_no_scene_or_fact_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """묶음 스냅샷에 장면·사실 행이 하나도 없으면 쥐지도 부르지도 않는다."""
    room, _ = await _three_part_room(db_client, db_session)
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake)

    assert fake.prompts == []
    assert await _impressions(db_session, room) == []
    assert await _attempts(db_session, room) == []


# --- 결과 ---------------------------------------------------------------------------------------


async def test_the_text_is_cut_at_its_limit(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, (first, _, _) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)

    await _generate(db_session, room, ImpressionLLMClient(MemoryImpressionResult(impression="가" * 700)))

    [row] = await _impressions(db_session, room)
    assert row.text == "가" * IMPRESSION_TEXT_MAX


async def test_a_blank_impression_writes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_failures(monkeypatch)
    room, (first, _, _) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)

    await _generate(db_session, room, ImpressionLLMClient(MemoryImpressionResult(impression="   ")))

    assert await _impressions(db_session, room) == []
    assert captured == []


async def test_a_result_read_before_a_forget_is_discarded(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """입력을 읽은 뒤 모델을 기다리는 사이 방의 잊기 세대가 오른다(그사이 방 주인이 장면이나 사실을 잊게 했다). 넣기 직전에 그것을
    보고 결과를 버린다 — 장애가 아니라 Bugsink 로 올리지 않는다."""
    captured = _capture_failures(monkeypatch)
    room, (first, _, _) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)

    async def _owner_forgets() -> MemoryImpressionResult:
        await db_session.execute(
            sa.update(ChatRoom)
            .where(ChatRoom.id == room.room_id)
            .values(memory_forget_generation=ChatRoom.memory_forget_generation + 1)
        )
        await db_session.commit()
        return MemoryImpressionResult(impression="잊은 장면이 담긴 인상")

    await _generate(db_session, room, ImpressionLLMClient(_owner_forgets))

    assert await _impressions(db_session, room) == []
    assert captured == []


async def test_a_model_error_stays_inside_and_later_background_tasks_still_run(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_failures(monkeypatch)
    room, (first, _, _) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)
    ran: list[str] = []

    async def _a_later_task() -> None:
        ran.append("later")

    error = LLMClientError("모델 실패")
    error.provider = "anthropic"
    tasks = BackgroundTasks()
    tasks.add_task(
        generate_pending_impression,
        _savepoint_factory(db_session),
        ImpressionLLMClient(error),
        **await _kwargs(db_session, room),
    )
    tasks.add_task(_a_later_task)
    await tasks()

    assert ran == ["later"]
    assert captured == ["anthropic"]
    assert await _impressions(db_session, room) == []


async def test_a_missing_channel_is_a_render_failure_without_a_call(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """세트에 인상 문안이 없으면(문안을 심기 전의 세트) 모델을 부르지 않고 렌더 실패로 올린다."""
    captured = _capture_failures(monkeypatch)
    room, (first, _, _) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="character")
    without_channel = [section for section in sections if section.channel != "memory_impression"]
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake, prompt_set=prompt_set, sections=without_channel)

    assert fake.prompts == []
    assert captured == ["prompt_render"]
    assert await _impressions(db_session, room) == []


def test_the_impression_module_never_reads_summaries_messages_or_notes() -> None:
    """입력은 장면·사실 행뿐이다 — 요약 글·원문 메시지·노트를 읽는 문장이 없다. 인상 행을 직접 지우지도 않는다(되감기와 같은
    이유로 스냅샷 CASCADE 에 맡긴다). 이 모듈이 두 기억 테이블을 실제로 읽는지도 본다 — 빈 모듈이면 부재 검사가 아무것도 말하지
    못한다."""
    assert memory_impressions.__file__ is not None
    source = Path(memory_impressions.__file__).read_text(encoding="utf-8")
    assert "ChatMemoryEpisode" in source and "ChatMemoryFact" in source
    for name in (
        "summary_text",
        "previous_text",
        "ChatMessage",
        "chat_messages",
        "memory_note",
        "load_current_summary",
    ):
        assert name not in source, name
    assert "delete(" not in source


# --- 시도 기록 ------------------------------------------------------------------------------------
#
# 묶음마다(가장 새 스냅샷마다) 시도 기록 한 행이 선점·재시도 상한·호출 원가를 겸한다 — 두 추출 기록과 같은 꼴이다. 같은 묶음을
# 두 작업이 함께 고른 경합은 커밋되는 독립 커넥션이 필요해 `test_chat_memory_rewind.py` 의 인상 경합 절에 있다.


def _plant_attempt(room: Room, snapshot_id: uuid.UUID, **overrides: Any) -> ChatMemoryImpressionAttempt:
    values: dict[str, Any] = {
        "chat_room_id": room.room_id,
        "snapshot_id": snapshot_id,
        "status": "running",
        "attempts": 1,
        "claimed_at": datetime.now(UTC),
    }
    values.update(overrides)
    return ChatMemoryImpressionAttempt(**values)


async def test_a_failing_group_is_called_three_times_and_then_left_alone(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """모델이 계속 실패하면 시도마다 기록이 `failed` 로 하나씩 오르고, 세 번째 실패 뒤에는 그 묶음이 가장 새 묶음으로 남아 있어도
    더 부르지 않는다. 기록이 없으면 다음 접기 전까지 턴마다 같은 묶음을 다시 부른다."""
    captured = _capture_failures(monkeypatch)
    room, (first, _, third) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)
    fake = ImpressionLLMClient(*(LLMClientError("모델 실패") for _ in range(3)))

    for attempt in range(1, 4):
        await _generate(db_session, room, fake)
        assert await _attempts(db_session, room) == [(third, "failed", attempt, False)]

    await _generate(db_session, room, fake)

    assert len(fake.prompts) == 3
    assert captured == ["gemini"] * 3
    assert await _impressions(db_session, room) == []


@pytest.mark.parametrize("failure", ["blank-text", "render-failure", "forgotten-during-the-call"])
async def test_every_way_of_writing_nothing_counts_as_a_failed_attempt(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """모델 실패만이 아니라 빈 글, 렌더 실패(세트에 인상 문안이 없다), 입력을 읽은 뒤 잊기 세대가 오른 것도 시도 하나를 쓴 실패다
    — 셋 다 그대로 두면 다음 턴이 같은 묶음을 다시 고르고, 상한이 없으면 끝없이 고른다."""
    _capture_failures(monkeypatch)
    room, (first, _, third) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)
    overrides: dict[str, Any] = {}
    if failure == "blank-text":
        fake = ImpressionLLMClient(MemoryImpressionResult(impression="   "))
    elif failure == "render-failure":
        fake = ImpressionLLMClient()
        prompt_set, sections = await load_active_prompt_set(db_session, lane="character")
        overrides = {
            "prompt_set": prompt_set,
            "sections": [section for section in sections if section.channel != "memory_impression"],
        }
    else:

        async def _owner_forgets() -> MemoryImpressionResult:
            await db_session.execute(
                sa.update(ChatRoom)
                .where(ChatRoom.id == room.room_id)
                .values(memory_forget_generation=ChatRoom.memory_forget_generation + 1)
            )
            await db_session.commit()
            return MemoryImpressionResult(impression="잊은 장면이 담긴 인상")

        fake = ImpressionLLMClient(_owner_forgets)

    await _generate(db_session, room, fake, **overrides)

    assert await _impressions(db_session, room) == []
    assert await _attempts(db_session, room) == [(third, "failed", 1, False)]


@pytest.mark.parametrize(
    ("status", "minutes_ago", "attempts", "retaken"),
    [
        pytest.param("running", 11, 1, True, id="stale-running"),
        pytest.param("running", 11, 3, False, id="stale-running-at-the-attempt-limit"),
        pytest.param("running", 9, 1, False, id="fresh-running"),
        pytest.param("failed", 0, 2, True, id="failed-twice"),
        pytest.param("failed", 0, 3, False, id="failed-three-times"),
    ],
)
async def test_a_stale_or_failed_claim_is_retaken_within_the_attempt_limit(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    status: str,
    minutes_ago: int,
    attempts: int,
    retaken: bool,
) -> None:
    """작업이 죽어(배포 교체) `running` 이 남으면 10분이 지난 뒤 다음 작업이 다시 쥔다. 10분 안의 `running` 은 아직 도는 작업의
    것이라 건드리지 않는다. 실패도 다시 쥔다. 어느 쪽이든 시도는 세 번까지다."""
    room, (first, _, third) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)
    db_session.add(
        _plant_attempt(
            room,
            third,
            status=status,
            attempts=attempts,
            claimed_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        )
    )
    await db_session.commit()
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake)

    assert len(fake.prompts) == (1 if retaken else 0)
    if retaken:
        assert await _attempts(db_session, room) == [(third, "done", attempts + 1, True)]
        assert len(await _impressions(db_session, room)) == 1
    else:
        assert await _attempts(db_session, room) == [(third, status, attempts, False)]
        assert await _impressions(db_session, room) == []


async def test_a_written_impression_records_its_model_and_tokens(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """성공한 시도는 `done` 이 되고, 그 호출의 모델 id 와 토큰 넷을 묶음 단위로 남긴다(입력은 캐시 포함 전체 — 사용량 기록과 같은
    뜻)."""
    room, (first, _, third) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)
    metadata = SimpleNamespace(
        prompt_token_count=5_000, cached_content_token_count=1_200, candidates_token_count=900, thoughts_token_count=0
    )

    await _generate(db_session, room, ImpressionLLMClient(usage_metadata=metadata))

    attempt = ChatMemoryImpressionAttempt
    rows = (
        await db_session.execute(
            sa.select(
                attempt.snapshot_id,
                attempt.status,
                attempt.attempts,
                attempt.model,
                attempt.prompt_tokens,
                attempt.cached_tokens,
                attempt.output_tokens,
                attempt.thoughts_tokens,
            ).where(attempt.chat_room_id == room.room_id)
        )
    ).all()
    assert [tuple(row) for row in rows] == [(third, "done", 1, "claude-haiku-5-5", 5_000, 1_200, 900, 0)]
    assert len(await _impressions(db_session, room)) == 1


async def _supersede_claim(db_session: AsyncSession, snapshot_id: uuid.UUID) -> None:
    """다른 작업이 낡은 선점을 다시 쥔 상태 — 선점 시각이 새것으로 바뀌고 시도가 하나 늘었다."""
    attempt = ChatMemoryImpressionAttempt
    await db_session.execute(
        sa.update(attempt)
        .where(attempt.snapshot_id == snapshot_id)
        .values(claimed_at=sa.func.clock_timestamp(), attempts=attempt.attempts + 1)
    )
    await db_session.commit()


async def _attempt_tokens(db_session: AsyncSession, room: Room) -> list[Any]:
    """방의 시도 기록 — (상태, 시도 수, 모델, 입력·캐시·출력 토큰)."""
    attempt = ChatMemoryImpressionAttempt
    rows = (
        await db_session.execute(
            sa.select(
                attempt.status,
                attempt.attempts,
                attempt.model,
                attempt.prompt_tokens,
                attempt.cached_tokens,
                attempt.output_tokens,
            ).where(attempt.chat_room_id == room.room_id)
        )
    ).all()
    return [tuple(row) for row in rows]


async def test_a_late_finisher_whose_claim_was_retaken_writes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """모델을 기다리는 사이(10분 넘게) 다른 작업이 낡은 선점을 다시 쥐었다. 늦게 끝난 쪽은 시도 기록을 `done` 으로 바꾸지도 인상
    행을 넣지도 않는다 — 다시 쥔 작업의 기록과 결과를 덮지 않는다."""
    room, (first, _, third) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)

    async def _another_job_retakes_the_claim() -> MemoryImpressionResult:
        await _supersede_claim(db_session, third)
        return MemoryImpressionResult(impression="늦게 끝난 인상")

    await _generate(db_session, room, ImpressionLLMClient(_another_job_retakes_the_claim))

    assert await _impressions(db_session, room) == []
    assert await _attempts(db_session, room) == [(third, "running", 2, False)]


async def test_a_failed_attempt_keeps_the_tokens_it_spent(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """응답을 받고 나서 실패한 시도도 토큰을 썼다 — 실패 기록에 남기고, 다시 쥔 시도의 토큰은 더한다."""
    _capture_failures(monkeypatch)
    room, (first, _, _) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)
    metadata = SimpleNamespace(
        prompt_token_count=1_000, cached_content_token_count=100, candidates_token_count=300, thoughts_token_count=0
    )
    fake = ImpressionLLMClient(LLMClientError("파싱 실패"), usage_metadata=metadata)

    await _generate(db_session, room, fake)

    assert await _attempt_tokens(db_session, room) == [("failed", 1, "claude-haiku-5-5", 1_000, 100, 300)]

    await _generate(db_session, room, fake)

    assert await _attempt_tokens(db_session, room) == [("done", 2, "claude-haiku-5-5", 2_000, 200, 600)]


async def test_a_late_failure_does_not_mark_a_claim_another_job_retook(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """모델을 기다리는 사이 다른 작업이 선점을 다시 쥐었고, 그 뒤 원래 작업의 모델 호출이 실패했다. 늦은 실패는 다시 쥔 작업의
    `running` 을 `failed` 로 덮지 않는다 — 덮으면 도는 작업이 있는데도 다음 작업이 또 쥐어 같은 묶음에 모델을 한 번 더 부른다."""
    _capture_failures(monkeypatch)
    room, (first, _, third) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)

    async def _retaken_then_failed() -> MemoryImpressionResult:
        await _supersede_claim(db_session, third)
        raise LLMClientError("늦은 실패")

    await _generate(db_session, room, ImpressionLLMClient(_retaken_then_failed))

    assert await _attempts(db_session, room) == [(third, "running", 2, False)]


@pytest.mark.parametrize("path", ["rewind-into-the-group", "reset", "room-deletion"])
async def test_rewind_reset_and_room_deletion_leave_no_attempt(
    db_client: httpx.AsyncClient, db_session: AsyncSession, path: str
) -> None:
    """시도 기록은 묶음의 가장 새 스냅샷에 걸린다. 되감기가 묶음의 가장 오래된 스냅샷까지 지우든, 초기화든, 방 삭제든 스냅샷 DELETE
    의 CASCADE 가 기록을 함께 지운다 — 되감기·방 삭제 코드는 이 테이블을 모르고, 모르는 옛 이미지의 DELETE 도 FK 위반이 되지 않는다."""
    room, (_, _, third) = await _three_part_room(db_client, db_session)
    db_session.add(_plant_attempt(room, third, status="failed", attempts=3))
    await db_session.commit()
    assert len(await _attempts(db_session, room)) == 1

    if path == "rewind-into-the-group":
        first_user = room.turns[5][0]
        await rewind_memory(db_session, room.room_id, (first_user.created_at, first_user.id))
    elif path == "reset":
        await rewind_memory(db_session, room.room_id, None)
    else:
        await delete_chat_rooms(db_session, [room.room_id])
    await db_session.commit()

    assert await _attempts(db_session, room) == []


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"status": "pending"}, id="unknown-status"),
        pytest.param({"attempts": 0}, id="zero-attempts"),
    ],
)
async def test_the_attempt_table_rejects_rows_outside_its_checks(
    db_client: httpx.AsyncClient, db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    """`alembic check` 는 CHECK 를 비교하지 않는다 — 이 거부가 두 제약의 유일한 검증이다. 같은 스냅샷에 경계 안쪽 값(`attempts`
    1, 알려진 상태)은 들어가므로 거부가 그 칸 값 때문임이 드러난다."""
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_plant_attempt(room, snapshot_id, **overrides))
            await db_session.flush()

    db_session.add(_plant_attempt(room, snapshot_id, status="failed", attempts=1))
    await db_session.flush()


# --- 지워지는 길 ----------------------------------------------------------------------------------


async def _room_with_an_impression(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[Room, list[uuid.UUID], uuid.UUID, uuid.UUID]:
    """인상 한 행이 있는 30턴 방. (방, 스냅샷 셋, 장면 id, 사실 id)."""
    room, snapshots = await _three_part_room(db_client, db_session)
    scene_id = await _scene(db_session, room, snapshots[0])
    fact_id = await _fact(db_session, room, snapshots[1])
    await _generate(db_session, room, ImpressionLLMClient())
    assert len(await _impressions(db_session, room)) == 1
    return room, snapshots, scene_id, fact_id


async def test_forgetting_a_scene_removes_every_impression_of_the_room_and_raises_the_generation(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """잊는 장면이 인상의 근거든 아니든, 인상이 매달린 스냅샷과 다른 스냅샷의 장면이든 그 방의 인상은 모두 지워진다.
    다른 방의 인상은 남는다."""
    room, snapshots, _, _ = await _room_with_an_impression(db_client, db_session)
    other, *_ = await _room_with_an_impression(db_client, db_session)
    # 인상은 묶음의 가장 새 스냅샷(snapshots[2])에 매달린다. 잊는 장면을 그보다 오래된 스냅샷에 두어야 잊는 장면의
    # 스냅샷으로만 좁힌 DELETE 가 인상을 남겨 드러난다.
    unrelated = await _scene(db_session, room, snapshots[1], ordinal=1, title="근거 아닌 장면", detail="나중 장면.")
    generation = await _generation(db_session, room)

    await forget_episode(db_session, room.room_id, unrelated)
    await db_session.commit()

    assert await _impressions(db_session, room) == []
    assert len(await _impressions(db_session, other)) == 1
    assert await _generation(db_session, room) == generation + 1


async def test_forgetting_a_fact_key_removes_every_impression_of_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, _, _, _ = await _room_with_an_impression(db_client, db_session)
    generation = await _generation(db_session, room)

    await forget_fact_key(db_session, room.room_id, "relation|민수|지아")
    await db_session.commit()

    assert await _impressions(db_session, room) == []
    assert await _generation(db_session, room) == generation + 1


async def test_the_newest_group_is_written_again_after_a_forget(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """잊기는 그 방의 인상과 함께 `done` 시도 기록을 지운다. 그 묶음이 아직 가장 새 묶음이면 다음 생성이 남은 행으로 인상을 다시
    만든다 — `done` 이 남으면 선점이 끝난 묶음으로 보고 다시 쥐지 않아 인상이 돌아오지 않는다."""
    room, snapshots, scene_id, _ = await _room_with_an_impression(db_client, db_session)
    assert await _attempts(db_session, room) == [(snapshots[2], "done", 1, True)]

    await forget_episode(db_session, room.room_id, scene_id)
    await db_session.commit()

    assert await _attempts(db_session, room) == []

    fake = ImpressionLLMClient()
    await _generate(db_session, room, fake)

    assert len(fake.prompts) == 1
    assert len(await _impressions(db_session, room)) == 1
    assert await _attempts(db_session, room) == [(snapshots[2], "done", 1, True)]


async def test_a_group_that_failed_three_times_stays_stopped_after_a_forget(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """잊기는 `failed` 시도 기록을 남긴다 — 재시도 상한의 기록이라, 지우면 세 번 실패한 묶음을 잊을 때마다 세 번씩 다시 부른다."""
    room, (first, second, third) = await _three_part_room(db_client, db_session)
    scene_id = await _scene(db_session, room, first)
    await _fact(db_session, room, second)
    db_session.add(_plant_attempt(room, third, status="failed", attempts=3))
    await db_session.commit()

    await forget_episode(db_session, room.room_id, scene_id)
    await db_session.commit()
    fake = ImpressionLLMClient()
    await _generate(db_session, room, fake)

    assert fake.prompts == []
    assert await _attempts(db_session, room) == [(third, "failed", 3, False)]


@pytest.mark.parametrize("path", ["rewind-into-the-group", "reset", "room-deletion"])
async def test_rewind_reset_and_room_deletion_leave_no_impression(
    db_client: httpx.AsyncClient, db_session: AsyncSession, path: str
) -> None:
    """되감기가 묶음의 가장 오래된 스냅샷까지 지우든, 초기화든, 방 삭제든 스냅샷 CASCADE 가 인상을 함께 지운다."""
    room, _, _, _ = await _room_with_an_impression(db_client, db_session)

    if path == "rewind-into-the-group":
        first_user = room.turns[5][0]
        await rewind_memory(db_session, room.room_id, (first_user.created_at, first_user.id))
    elif path == "reset":
        await rewind_memory(db_session, room.room_id, None)
    else:
        await delete_chat_rooms(db_session, [room.room_id])
    await db_session.commit()

    assert await _impressions(db_session, room) == []


# --- 제약 ---------------------------------------------------------------------------------------


async def _insert_impression(db_session: AsyncSession, room: Room, snapshot_id: uuid.UUID, **overrides: Any) -> None:
    values: dict[str, Any] = {
        "chat_room_id": room.room_id,
        "snapshot_id": snapshot_id,
        "first_cursor_created_at": room.turns[10][1].created_at,
        "first_cursor_message_id": room.turns[10][1].id,
        "text": "인상",
        "episode_ids": [],
        "fact_ids": [],
    }
    values.update(overrides)
    db_session.add(ChatMemoryImpression(**values))
    await db_session.flush()


_CHECK_CASES: Sequence[Any] = [
    pytest.param({"text": ""}, id="empty-text"),
    pytest.param({"text": "가" * (IMPRESSION_TEXT_MAX + 1)}, id="text-one-over"),
    pytest.param({"episode_ids": {"id": "x"}}, id="episode-ids-not-array"),
    pytest.param({"fact_ids": "x"}, id="fact-ids-not-array"),
]


@pytest.mark.parametrize("overrides", _CHECK_CASES)
async def test_the_table_rejects_rows_outside_its_checks(
    db_client: httpx.AsyncClient, db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _insert_impression(db_session, room, snapshot_id, **overrides)


async def test_the_table_accepts_the_limits_and_one_row_per_snapshot(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)

    await _insert_impression(db_session, room, snapshot_id, text="가" * IMPRESSION_TEXT_MAX)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _insert_impression(db_session, room, snapshot_id)
