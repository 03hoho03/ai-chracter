"""요약 접기 몇 번마다 방 하나에 인상 한 행을 쌓는다(저장만 — 생성에 싣지 않는다).

- 언제: 스위치(`memory_impressions_write`)가 켜져 있으면 턴 뒤 접기·두 추출 예약 **뒤에** 따로 예약한다. 꺼져 있으면 예약하지
  않는다(턴의 호출·트랜잭션이 스위치가 생기기 전과 같다). 작업은 방의 스냅샷 수가 `memory_impression_every_n_folds` 의 배수이고,
  가장 새 스냅샷에 인상이 아직 없고, 묶음(가장 새 것까지 N 개) 스냅샷의 장면·사실 추출이 모두 끝났을 때만 모델을 부른다. 그
  턴의 레인과 글쓰기 모델이 기억 사용 범위 밖이면 아무것도 하지 않는다.
- 입력: 묶음 스냅샷의 장면·사실 행 중 아는 사람이 정해지지 않은 것뿐이다. 요약 글·원문 창은 싣지 않는다 — 그래서 비밀 행이
  있든 없든 프롬프트가 바이트까지 같다.
- 쓰기: 마지막 트랜잭션은 가장 새 스냅샷을 `FOR KEY SHARE` 로 잠근 뒤 방의 잊기 세대를 다시 읽고, 입력을 읽을 때와 다르면 결과를
  버린다. 잊게 하기(장면·사실 모두)는 그 방의 인상을 전부 지우고 잊기 세대를 올린다.

진짜 두 세션의 경합(잊기가 생성 커밋을 기다리는가)은 `test_chat_memory_rewind.py` 의 커밋되는 독립 커넥션 절에 있다. 문안은 아직
DB 세트에 없어 테스트가 합성 섹션을 직접 넘긴다.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
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
from api.db.models import ChatMemoryImpression, ChatRoom, ChatRoomMemorySnapshot
from api.db.models.chat import IMPRESSION_TEXT_MAX
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
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
    `open_sessions` 가 있으면 인상 호출 순간 열린 루트 트랜잭션 수를 적는다."""

    def __init__(self, *outcomes: ImpressionOutcome, open_sessions: set[int] | None = None) -> None:
        self.outcomes = list(outcomes)
        self.open_sessions = open_sessions
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
        "sections": [*sections, *_impression_sections(prompt_set)],
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


async def test_a_due_group_becomes_one_impression_built_only_from_public_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """묶음 세 스냅샷의 공개 장면·사실만 입력이 된다. 아는 사람이 정해진 장면·사실은 프롬프트에도 근거 id 에도 없다. 행은 가장 새
    스냅샷에 걸리고 첫 커서는 가장 오래된 스냅샷의 것이다. 글은 앞뒤 공백을 걷는다. 모델을 기다리는 동안 커넥션을 쥐지 않는다."""
    room, (first, second, third) = await _three_part_room(db_client, db_session)
    public_scene = await _scene(db_session, room, first, title="첫 장면", detail="정류장에서 우산을 나눠 썼다.")
    await _scene(db_session, room, second, title="[비밀 장면]", detail="[비밀 장면 내용]", known_by=["지아"])
    later_scene = await _scene(db_session, room, third, title="둘째 장면", detail="빵집 앞에서 다시 만났다.")
    public_fact = await _fact(db_session, room, second)
    await _fact(
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
        "[장면]\n- 첫 장면: 정류장에서 우산을 나눠 썼다.\n- 둘째 장면: 빵집 앞에서 다시 만났다.\n\n"
        "[사실]\n- 민수 → 지아: 소꿉친구 (confirmed)\n- 민수 / 직업: 제빵사 (claimed)"
    ]
    assert "비밀" not in fake.prompts[0] and "SUMMARY" not in fake.prompts[0] and "[U" not in fake.prompts[0]
    oldest = room.turns[10][1]
    assert await _impressions(db_session, room) == [
        (
            room.room_id,
            third,
            oldest.created_at,
            oldest.id,
            "서로를 믿기 시작했다.",
            [str(public_scene), str(later_scene)],
            [str(public_fact), str(attribute_fact)],
        )
    ]


async def test_the_prompt_is_byte_identical_with_or_without_secret_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 공개 행을 가진 두 방 — 한 방에만 비밀 장면·사실을 더 심는다. 두 방의 프롬프트가 바이트까지 같다(입력 제외가 행의 칸
    하나로 정해지고, 순서가 스냅샷 커서·순번으로 정해진다)."""
    prompts: list[str] = []
    for with_secrets in (False, True):
        room, (first, second, third) = await _three_part_room(db_client, db_session)
        await _scene(db_session, room, first, title="첫 장면", detail="우산.")
        await _fact(db_session, room, third, ordinal=1, value="이웃")
        if with_secrets:
            await _scene(db_session, room, first, ordinal=1, title="[비밀]", detail="[비밀]", known_by=["지아"])
            await _fact(db_session, room, third, ordinal=0, value="[비밀 사이]", known_by=["민수"])
        await _scene(db_session, room, second, title="둘째 장면", detail="빵집.")
        fake = ImpressionLLMClient()
        await _generate(db_session, room, fake)
        prompts += fake.prompts

    assert len(prompts) == 2
    assert prompts[0] == prompts[1]


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


async def test_nothing_is_called_when_every_row_in_the_group_is_secret(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, (first, second, _) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first, known_by=["지아"])
    await _fact(db_session, room, second, known_by=["민수"])
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake)

    assert fake.prompts == []
    assert await _impressions(db_session, room) == []


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
    """활성 세트에 인상 문안이 없으면(문안을 심기 전) 모델을 부르지 않고 렌더 실패로 올린다."""
    captured = _capture_failures(monkeypatch)
    room, (first, _, _) = await _three_part_room(db_client, db_session)
    await _scene(db_session, room, first)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="character")
    fake = ImpressionLLMClient()

    await _generate(db_session, room, fake, prompt_set=prompt_set, sections=sections)

    assert fake.prompts == []
    assert captured == ["prompt_render"]
    assert await _impressions(db_session, room) == []


def test_the_impression_module_never_reads_summaries_messages_or_notes() -> None:
    """입력은 장면·사실 행뿐이다 — 요약 글·원문 메시지·노트를 읽는 문장이 없다. 인상 행을 직접 지우지도 않는다(되감기와 같은
    이유로 스냅샷 CASCADE 에 맡긴다). 이 모듈이 두 기억 테이블을 실제로 읽는지도 본다 — 빈 모듈이면 부재 검사가 아무것도 말하지
    못한다."""
    assert memory_impressions.__file__ is not None
    source = Path(memory_impressions.__file__).read_text(encoding="utf-8")
    assert "ChatMemoryEpisode" in source and "ChatMemoryFact" in source and "known_by" in source
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
    """잊는 장면이 인상의 근거든 아니든 그 방의 인상은 모두 지워진다. 다른 방의 인상은 남는다."""
    room, snapshots, _, _ = await _room_with_an_impression(db_client, db_session)
    other, *_ = await _room_with_an_impression(db_client, db_session)
    unrelated = await _scene(db_session, room, snapshots[2], ordinal=1, title="근거 아닌 장면", detail="나중 장면.")
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
