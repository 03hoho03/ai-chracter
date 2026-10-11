"""요약 접기가 접은 대화 구간을 장면 기억으로 뽑는다.

- 언제: 스위치(`memory_episodes_extract`)가 켜져 있고 생성 윈도우가 켜져 있을 때, 턴 뒤 접기 예약 **뒤에** 추출을 예약한다.
  꺼져 있으면 아무것도 예약하지 않는다(턴의 호출·트랜잭션이 스위치가 생기기 전과 같다).
- 무엇을: 추출 기록이 없거나 다시 시도할 수 있는 스냅샷 중 커서가 가장 오래된 것 하나. 창은 직전 스냅샷 커서 다음부터
  그 스냅샷 커서까지(오프닝 제외)이고, 직전 스냅샷 장면의 마지막 제목 둘을 함께 싣는다. 노트·스탯·계정 정보는 싣지 않는다.
- 결과: 서버가 빈 본문을 버리고 앞 10개만 남긴 뒤 제목·본문을 자르고 줄 번호를 메시지 키·턴으로 바꿔 넣는다. 명사는 모델
  명사의 공백 조각과 제목·본문의 조사 뗀 토큰(형태소기 없음)이다.
- 실패: 호출·렌더·파싱·제약 위반은 실패 기록이 되고 세 번까지 다시 쥔다. 스냅샷이 그사이 지워진 것은 실패가 아니다.

추출 함수를 직접 부르는 테스트는 세션마다 SAVEPOINT 를 여는 팩토리를 쓴다 — 추출의 각 트랜잭션 커밋이 그 SAVEPOINT 만
확정하고, 제약 위반처럼 진짜로 망가진 트랜잭션이 테스트 트랜잭션까지 번지지 않는다. 진짜 두 세션의 경합은
`test_chat_memory_rewind.py` 의 커밋되는 독립 커넥션 절에 있다.
"""

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_episodes, memory_nouns
from api.chat.memory_episodes import EpisodeDraft, extract_pending_episode, normalize_episodes
from api.chat.memory_nouns import episode_nouns, rule_tokens
from api.chat.prompt_builder import (
    MemoryEpisodeItem,
    MemoryEpisodeResult,
    MemorySummaryResult,
    PromptLane,
    PromptNames,
    StatRuleJudgmentResult,
    load_active_prompt_set,
)
from api.core.config import settings
from api.db.models import (
    ChatMemoryEpisode,
    ChatMemoryExtraction,
    ChatMessage,
    ChatMessageRole,
    ChatRoomMemorySnapshot,
)
from api.db.models.chat import EPISODE_DETAIL_MAX, EPISODE_NOUNS_MAX, EPISODE_TITLE_MAX
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, collect_usage
from factories import (
    PRODUCTION_ENV_NAMES,
    Room,
    _clear_llm_override,
    _make_memory_episode,
    _make_memory_extraction,
    _open_room,
    _open_transaction_probe,
    _override_llm_client,
    _parse_sse_events,
    _plant_snapshot,
    load_production_env,
)

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "memory_recall_vectors.json").read_text(encoding="utf-8"))

EpisodeOutcome = MemoryEpisodeResult | Exception | Callable[[], Awaitable[MemoryEpisodeResult]]


def _item(**overrides: Any) -> MemoryEpisodeItem:
    values: dict[str, Any] = {
        "title": "밀알당에 간 날",
        "detail": "밀알당에서 소금빵을 먹었다.",
        "nouns": ["밀알당", "소금빵"],
        "keywords": ["빵집"],
        "asserted_by": "user",
        "evidence": ["소금빵 진짜 맛있다"],
        "importance": 3,
        "start_line": 1,
        "end_line": 2,
    }
    values.update(overrides)
    return MemoryEpisodeItem(**values)


def _result(*items: MemoryEpisodeItem) -> MemoryEpisodeResult:
    return MemoryEpisodeResult(episodes=list(items))


class EpisodeLLMClient(LLMClient):
    """생성은 고정 응답, 요약은 고정 본문, 스탯 판정은 변화 없음. 장면 추출에는 `outcomes` 를 차례로 준다(결과는 그대로,
    예외는 raise, 콜러블은 불러서 그 결과를 — 호출 도중의 경합을 흉내 낸다). 다 쓰면 장면 하나짜리 기본 결과다.
    `usage_metadata` 가 있으면 그 사용량을 호출의 `usage_sink` 에 더한다(공급자 구현이 하는 일과 같다).
    `open_sessions` 가 있으면 추출 호출 순간 열린 루트 트랜잭션 수를 적는다."""

    def __init__(
        self,
        *outcomes: EpisodeOutcome,
        usage_metadata: object | None = None,
        open_sessions: set[int] | None = None,
    ) -> None:
        self.outcomes = list(outcomes)
        self.usage_metadata = usage_metadata
        self.open_sessions = open_sessions
        self.episode_prompts: list[str] = []
        self.episode_usages: list[LLMCallContext] = []
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
        assert response_schema is MemoryEpisodeResult, response_schema
        self.episode_prompts.append(prompt)
        self.episode_usages.append(usage)
        if self.open_sessions is not None:
            self.open_at_call.append(len(self.open_sessions))
        if self.usage_metadata is not None:
            collect_usage(usage, "claude-haiku-5-5", self.usage_metadata)
        outcome = self.outcomes.pop(0) if self.outcomes else _result(_item())
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return await outcome()
        return outcome


def _savepoint_factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _extract(db_session: AsyncSession, room: Room, llm: LLMClient, *, lane: PromptLane = "character") -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane)
    await extract_pending_episode(
        _savepoint_factory(db_session),
        llm,
        room_id=room.room_id,
        user_id=room.user_id,
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=lane == "story",
        names=PromptNames(persona_name=None, char_name=None),
    )


async def _snapshot_id(db_session: AsyncSession, room: Room, turn: int) -> uuid.UUID:
    assistant = room.turns[turn][1]
    snapshot_id = await db_session.scalar(
        sa.select(ChatRoomMemorySnapshot.id).where(
            ChatRoomMemorySnapshot.chat_room_id == room.room_id,
            ChatRoomMemorySnapshot.cursor_message_id == assistant.id,
        )
    )
    assert snapshot_id is not None
    return snapshot_id


async def _plant(db_session: AsyncSession, room: Room, turn: int, *, extracted: bool = False) -> uuid.UUID:
    """턴 `turn` 의 응답을 커서로 둔 스냅샷을 심는다. `extracted` 면 그 스냅샷의 추출이 끝난 기록도 함께."""
    await _plant_snapshot(db_session, room, turn=turn, text=f"[S{turn}]")
    snapshot_id = await _snapshot_id(db_session, room, turn)
    if extracted:
        db_session.add(_make_memory_extraction(room.room_id, snapshot_id, episode_count=0))
        await db_session.commit()
    return snapshot_id


async def _episodes(db_session: AsyncSession, room: Room) -> list[Any]:
    return list(
        (
            await db_session.execute(
                sa.select(
                    ChatMemoryEpisode.snapshot_id,
                    ChatMemoryEpisode.chat_room_id,
                    ChatMemoryEpisode.ordinal,
                    ChatMemoryEpisode.title,
                    ChatMemoryEpisode.start_message_id,
                    ChatMemoryEpisode.end_message_id,
                    ChatMemoryEpisode.start_turn,
                    ChatMemoryEpisode.end_turn,
                    ChatMemoryEpisode.nouns,
                )
                .where(ChatMemoryEpisode.chat_room_id == room.room_id)
                .order_by(ChatMemoryEpisode.end_created_at, ChatMemoryEpisode.ordinal)
            )
        ).all()
    )


async def _extractions(db_session: AsyncSession, room: Room) -> list[Any]:
    return list(
        (
            await db_session.execute(
                sa.select(
                    ChatMemoryExtraction.snapshot_id,
                    ChatMemoryExtraction.chat_room_id,
                    ChatMemoryExtraction.status,
                    ChatMemoryExtraction.attempts,
                    ChatMemoryExtraction.episode_count,
                    ChatMemoryExtraction.claimed_at,
                    ChatMemoryExtraction.finished_at,
                    ChatMemoryExtraction.model,
                    ChatMemoryExtraction.prompt_tokens,
                    ChatMemoryExtraction.cached_tokens,
                    ChatMemoryExtraction.output_tokens,
                    ChatMemoryExtraction.thoughts_tokens,
                ).where(ChatMemoryExtraction.chat_room_id == room.room_id)
            )
        ).all()
    )


def _capture_failures(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    captured: list[str] = []
    monkeypatch.setattr(
        memory_episodes, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    return captured


# --- 기준 벡터: 토큰화와 장면 명사 ----------------------------------------------------------
#
# 벡터는 평가 하네스의 시제품 구현이 낸 값이다(`fixtures/memory_recall_vectors.json`). 운영 코드는 하네스를 import 하지
# 않으므로 같은 규칙을 따로 구현했다 — 두 구현이 갈리면 평가 수치가 운영 동작을 말하지 못한다.


@pytest.mark.parametrize("case", VECTORS["tokenize"], ids=lambda case: case["text"])
def test_rule_tokens_match_the_reference_vectors(case: dict[str, Any]) -> None:
    assert rule_tokens(case["text"]) == case["tokens"]


@pytest.mark.parametrize("case", VECTORS["episodeNouns"], ids=lambda case: case["title"] or "blank-title")
def test_episode_nouns_match_the_reference_vectors(case: dict[str, Any]) -> None:
    nouns = episode_nouns(case["llmNouns"], case["title"], case["detail"])
    assert sorted(nouns) == case["nouns"]
    assert len(nouns) == len(set(nouns))


def test_stopwords_match_the_reference_vectors() -> None:
    assert sorted(memory_nouns.STOPWORDS) == VECTORS["stopwords"]


def test_episode_nouns_keep_model_pieces_first_and_stop_at_the_cap() -> None:
    """모델 명사 조각이 먼저, 제목·본문 토큰이 뒤 — 상한에 닿으면 본문 토큰부터 빠진다. 1자 모델 명사는 남는다."""
    model = [f"명사{index:02d}" for index in range(EPISODE_NOUNS_MAX - 1)] + ["빵"]
    nouns = episode_nouns(model, "제목낱말", "본문낱말을 적었다")
    assert nouns == [*model]
    assert episode_nouns(model[:-2], "제목낱말", "본문낱말을") == [*model[:-2], "제목낱말", "본문낱말"]


# --- 서버 정규화(순수 함수) ----------------------------------------------------------------

_T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _window(turns: int, *, start_turn: int = 1) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for turn in range(start_turn, start_turn + turns):
        for offset, role in ((0, ChatMessageRole.USER), (1, ChatMessageRole.ASSISTANT)):
            messages.append(
                ChatMessage(
                    id=uuid.UUID(int=2 * turn - 1 + offset),
                    role=role,
                    content=f"[{'U' if role == ChatMessageRole.USER else 'A'}{turn:02d}]",
                    created_at=_T0 + timedelta(seconds=2 * turn - 1 + offset),
                )
            )
    return messages


def _key(message: ChatMessage) -> tuple[datetime, uuid.UUID]:
    return (message.created_at, message.id)


def _one(item: MemoryEpisodeItem, *, turns: int = 3) -> EpisodeDraft:
    drafts = normalize_episodes(_result(item), _window(turns), turns_before=0)
    assert len(drafts) == 1
    return drafts[0]


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        pytest.param(EPISODE_TITLE_MAX, EPISODE_TITLE_MAX, id="at-limit"),
        pytest.param(EPISODE_TITLE_MAX + 1, EPISODE_TITLE_MAX, id="one-over"),
    ],
)
def test_normalization_cuts_the_title_at_its_limit(given: int, kept: int) -> None:
    assert _one(_item(title="가" * given)).title == "가" * kept


@pytest.mark.parametrize(
    ("detail", "kept"),
    [
        pytest.param("가" * EPISODE_DETAIL_MAX, "가" * EPISODE_DETAIL_MAX, id="at-limit"),
        pytest.param("가" * (EPISODE_DETAIL_MAX + 1), "가" * EPISODE_DETAIL_MAX, id="one-over-no-sentence-end"),
        # 상한 안 마지막 문장 끝(`.`·`다`·`요`) 뒤에서 자른다 — 단어 중간에서 끊지 않게.
        pytest.param(
            "가" * 250 + "갔다." + "나" * 48, "가" * 250 + "갔다.", id="one-over-cut-after-the-last-sentence-end"
        ),
        pytest.param("가" * 280 + "좋아요" + "나" * 18, "가" * 280 + "좋아요", id="one-over-cut-after-yo"),
    ],
)
def test_normalization_cuts_the_detail_at_its_limit(detail: str, kept: str) -> None:
    assert _one(_item(detail=detail)).detail == kept


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        pytest.param(0, 1, id="zero"),
        pytest.param(1, 1, id="one"),
        pytest.param(5, 5, id="five"),
        pytest.param(6, 5, id="six"),
        pytest.param(9, 5, id="nine"),
    ],
)
def test_normalization_clamps_importance_to_one_through_five(given: int, kept: int) -> None:
    assert _one(_item(importance=given)).importance == kept


@pytest.mark.parametrize("count", [EPISODE_NOUNS_MAX, EPISODE_NOUNS_MAX + 1], ids=["at-limit", "one-over"])
def test_normalization_caps_the_nouns(count: int) -> None:
    model = [f"명사{index:02d}" for index in range(count)]
    draft = _one(_item(nouns=model, title="ㄱ", detail="ㄴ"))
    assert draft.nouns == model[:EPISODE_NOUNS_MAX]


def test_normalization_drops_blank_details_before_keeping_the_first_ten() -> None:
    """빈 장면이 자리를 먹으면 창 뒤쪽 장면이 상한에 잘린다 — 빈 것을 먼저 버리고 나서 앞 10개를 남긴다."""
    items = [_item(detail="   ", title="빈 장면")] + [_item(title=f"장면{index:02d}") for index in range(11)]
    drafts = normalize_episodes(_result(*items), _window(3), turns_before=0)
    assert [draft.title for draft in drafts] == [f"장면{index:02d}" for index in range(10)]
    assert [draft.ordinal for draft in drafts] == list(range(10))


def test_normalization_trims_keywords_and_evidence_to_their_caps() -> None:
    draft = _one(
        _item(keywords=[" 하나 ", "", *[f"말{index}" for index in range(9)]], evidence=["근거1", " ", "근거2", "근거3"])
    )
    assert draft.keywords == ["하나", *[f"말{index}" for index in range(7)]]
    assert draft.evidence == ["근거1", "근거2"]


def test_a_blank_title_falls_back_to_the_start_of_the_detail() -> None:
    draft = _one(_item(title="  ", detail="나" * 70))
    assert draft.title == "나" * EPISODE_TITLE_MAX


@pytest.mark.parametrize(
    ("start_line", "end_line", "start_index", "end_index", "turns"),
    [
        pytest.param(1, 2, 0, 1, (11, 11), id="first-turn"),
        pytest.param(3, 5, 2, 4, (12, 13), id="user-line-to-user-line"),
        pytest.param(5, 3, 2, 4, (12, 13), id="reversed-lines-are-swapped"),
        pytest.param(0, 99, 0, 5, (11, 13), id="out-of-range-lines-are-clamped"),
        pytest.param(6, 6, 5, 5, (13, 13), id="last-line-only"),
    ],
)
def test_line_numbers_map_to_message_keys_and_turns(
    start_line: int, end_line: int, start_index: int, end_index: int, turns: tuple[int, int]
) -> None:
    """줄 번호는 1부터, 창 메시지 순서다. 턴은 오프닝을 뺀 어시스턴트 메시지 순번으로 센다 — 사용자 줄은 그 답이 붙을 턴,
    어시스턴트 줄은 자기 턴이다. 창 앞에 10턴이 있었다."""
    window = _window(3)
    draft = normalize_episodes(_result(_item(start_line=start_line, end_line=end_line)), window, turns_before=10)[0]
    assert (draft.start_key, draft.end_key) == (_key(window[start_index]), _key(window[end_index]))
    assert (draft.start_turn, draft.end_turn) == turns


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


async def test_extraction_is_not_scheduled_when_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert settings.memory_episodes_extract is False
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29)
    fake = EpisodeLLMClient()

    assert await _send(db_client, room, fake) == ["token", "done"]

    assert scheduled == ["fold_memory"]
    assert fake.episode_prompts == []
    assert await _episodes(db_session, room) == []
    assert await _extractions(db_session, room) == []


@pytest.mark.parametrize("lane", ["character", "story"])
async def test_extraction_runs_after_fold_on_the_new_snapshot(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, lane: str
) -> None:
    """접기가 같은 턴에 커밋한 스냅샷을 추출이 바로 본다(예약 순서대로 차례로 돈다). 추출이 LLM 을 기다리는 동안 DB
    커넥션을 쥐지 않는다."""
    monkeypatch.setattr(settings, "memory_episodes_extract", True)
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29, lane=lane)
    await db_session.commit()

    with _open_transaction_probe() as open_sessions:
        fake = EpisodeLLMClient(_result(_item(start_line=3, end_line=20)), open_sessions=open_sessions)
        events = await _send(db_client, room, fake)

    assert events[-1] == "done"
    assert scheduled == ["fold_memory", "extract_pending_episode"]
    assert len(fake.episode_prompts) == 1
    assert fake.open_at_call == [0]
    usage = fake.episode_usages[0]
    assert (usage.call_site, usage.room_id, usage.user_id) == ("chat_memory_episode", room.room_id, room.user_id)
    prompt = fake.episode_prompts[0]
    assert "[1] " in prompt and "[U01]" in prompt and "[A10]" in prompt
    assert "[U11]" not in prompt
    snapshot_id = await _snapshot_id(db_session, room, 10)
    snapshot_room = await db_session.scalar(
        sa.select(ChatRoomMemorySnapshot.chat_room_id).where(ChatRoomMemorySnapshot.id == snapshot_id)
    )
    episodes = await _episodes(db_session, room)
    assert [(row.snapshot_id, row.chat_room_id) for row in episodes] == [(snapshot_id, snapshot_room)]
    assert (episodes[0].start_message_id, episodes[0].end_message_id) == (room.turns[2][0].id, room.turns[10][1].id)
    assert (episodes[0].start_turn, episodes[0].end_turn) == (2, 10)
    extractions = await _extractions(db_session, room)
    assert [
        (row.snapshot_id, row.chat_room_id, row.status, row.attempts, row.episode_count) for row in extractions
    ] == [(snapshot_id, snapshot_room, "done", 1, 1)]
    assert extractions[0].finished_at is not None


async def test_extraction_follows_the_generation_window_switch(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """생성 윈도우가 꺼져 있으면 접기가 없다 — 추출 스위치가 켜져 있어도 추출도 예약하지 않는다."""
    monkeypatch.setattr(settings, "memory_episodes_extract", True)
    monkeypatch.setattr(settings, "memory_window_generation", False)
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29)

    await _send(db_client, room, EpisodeLLMClient())

    assert scheduled == []
    assert await _extractions(db_session, room) == []


# --- 창·입력 ----------------------------------------------------------------------------------


async def test_extraction_window_starts_after_previous_snapshot_cursor(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=20)
    await _plant(db_session, room, 10, extracted=True)
    second = await _plant(db_session, room, 20)
    fake = EpisodeLLMClient(_result(_item(start_line=1, end_line=20)))

    await _extract(db_session, room, fake)

    lines = fake.episode_prompts[0].splitlines()
    numbered = [line for line in lines if line.startswith("[") and line.split("]", 1)[0][1:].isdigit()]
    assert len(numbered) == 20
    assert numbered[0].startswith("[1] ") and "[U11]" in numbered[0]
    assert numbered[-1].startswith("[20] ") and "[A20]" in numbered[-1]
    assert not any("[A10]" in line or "[U10]" in line for line in lines)
    episodes = await _episodes(db_session, room)
    assert [(row.snapshot_id, row.start_message_id, row.end_message_id) for row in episodes] == [
        (second, room.turns[11][0].id, room.turns[20][1].id)
    ]
    assert (episodes[0].start_turn, episodes[0].end_turn) == (11, 20)


async def test_extraction_prompt_carries_previous_scene_titles(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """직전 스냅샷 장면의 마지막 제목 둘을, 일어난 순서대로 싣는다."""
    room = await _open_room(db_client, db_session, turns=20)
    first = await _plant(db_session, room, 10, extracted=True)
    for ordinal in range(3):
        db_session.add(_make_memory_episode(room.room_id, first, ordinal=ordinal, title=f"[T{ordinal}]"))
    await db_session.commit()
    await _plant(db_session, room, 20)
    fake = EpisodeLLMClient()

    await _extract(db_session, room, fake)

    prompt = fake.episode_prompts[0]
    assert "[T1]\n[T2]" in prompt
    assert "[T0]" not in prompt


async def test_first_window_sends_no_previous_scene_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)
    fake = EpisodeLLMClient()

    await _extract(db_session, room, fake)

    assert "[앞 구간의 마지막 장면]" not in fake.episode_prompts[0]
    assert "[U01]" in fake.episode_prompts[0]


async def test_oldest_pending_snapshot_is_extracted_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=20)
    first = await _plant(db_session, room, 10)
    second = await _plant(db_session, room, 20)
    fake = EpisodeLLMClient()

    await _extract(db_session, room, fake)
    assert [row.snapshot_id for row in await _extractions(db_session, room)] == [first]
    assert "[U01]" in fake.episode_prompts[0] and "[U11]" not in fake.episode_prompts[0]

    await _extract(db_session, room, fake)
    assert {row.snapshot_id for row in await _extractions(db_session, room)} == {first, second}
    assert "[U11]" in fake.episode_prompts[1] and "[A10]" not in fake.episode_prompts[1]

    await _extract(db_session, room, fake)
    assert len(fake.episode_prompts) == 2


def test_episode_module_never_touches_memory_note() -> None:
    """노트는 사용자만 고치는 칸이다 — 추출 경로가 그 컬럼을 읽거나 쓰는 문장을 갖지 않는다는 것을 구조로 지킨다."""
    for module in (memory_episodes, memory_nouns):
        assert module.__file__ is not None
        assert "memory_note" not in Path(module.__file__).read_text(encoding="utf-8")


# --- 결과·실패 ------------------------------------------------------------------------------


async def test_empty_episode_list_marks_extraction_done(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)

    await _extract(db_session, room, EpisodeLLMClient(_result()))

    assert await _episodes(db_session, room) == []
    assert [(row.snapshot_id, row.status, row.episode_count) for row in await _extractions(db_session, room)] == [
        (snapshot_id, "done", 0)
    ]


async def test_failed_extraction_retries_up_to_three_times(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)
    fake = EpisodeLLMClient(*(LLMClientError("boom") for _ in range(3)))

    for attempt in range(1, 4):
        await _extract(db_session, room, fake)
        assert [(row.status, row.attempts) for row in await _extractions(db_session, room)] == [("failed", attempt)]

    await _extract(db_session, room, fake)

    assert len(fake.episode_prompts) == 3
    assert captured == ["gemini"] * 3
    assert await _episodes(db_session, room) == []


async def test_a_retry_after_failure_succeeds(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)
    fake = EpisodeLLMClient(LLMClientError("boom"))

    await _extract(db_session, room, fake)
    await _extract(db_session, room, fake)

    assert [(row.status, row.attempts, row.episode_count) for row in await _extractions(db_session, room)] == [
        ("done", 2, 1)
    ]
    assert len(await _episodes(db_session, room)) == 1


async def test_check_violation_counts_as_failed_attempt(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정규화를 지나고도 CHECK 에 걸리면(정규화의 결함) 경합이 아니라 실패다 — 무한히 다시 쥐지 않고 시도를 센다."""
    captured = _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)
    real_normalize = memory_episodes.normalize_episodes

    def _broken_normalize(*args: Any, **kwargs: Any) -> list[EpisodeDraft]:
        drafts = real_normalize(*args, **kwargs)
        return [EpisodeDraft(**{**draft.__dict__, "importance": 9}) for draft in drafts]

    monkeypatch.setattr(memory_episodes, "normalize_episodes", _broken_normalize)
    await _extract(db_session, room, EpisodeLLMClient())

    assert [(row.status, row.attempts) for row in await _extractions(db_session, room)] == [("failed", 1)]
    assert captured == ["db"]
    assert await _episodes(db_session, room) == []

    monkeypatch.setattr(memory_episodes, "normalize_episodes", real_normalize)
    await _extract(db_session, room, EpisodeLLMClient())

    assert [(row.status, row.attempts) for row in await _extractions(db_session, room)] == [("done", 2)]


async def test_extraction_records_token_usage(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant(db_session, room, 10)
    metadata = SimpleNamespace(
        prompt_token_count=5_000, cached_content_token_count=1_200, candidates_token_count=900, thoughts_token_count=0
    )

    await _extract(db_session, room, EpisodeLLMClient(usage_metadata=metadata))

    row = (await _extractions(db_session, room))[0]
    assert (row.model, row.prompt_tokens, row.cached_tokens, row.output_tokens, row.thoughts_tokens) == (
        "claude-haiku-5-5",
        5_000,
        1_200,
        900,
        0,
    )


async def test_summary_edit_does_not_discard_extraction(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """요약 편집은 스냅샷을 제자리에서 고치고 기억 버전을 올리지만 창 원문은 그대로다 — 추출은 버리지 않는다."""
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)

    async def _user_edits_the_summary() -> MemoryEpisodeResult:
        response = await db_client.put(
            f"/chat-rooms/{room.room_id}/memory/summary", json={"summary": "[EDITED]", "version": 0}
        )
        assert response.status_code == 200, response.text
        return _result(_item())

    await _extract(db_session, room, EpisodeLLMClient(_user_edits_the_summary))

    assert (
        await db_session.scalar(
            sa.select(ChatRoomMemorySnapshot.summary_text).where(ChatRoomMemorySnapshot.id == snapshot_id)
        )
        == "[EDITED]"
    )
    assert [row.snapshot_id for row in await _episodes(db_session, room)] == [snapshot_id]
    assert [row.status for row in await _extractions(db_session, room)] == ["done"]


async def test_snapshot_deleted_before_the_claim_is_skipped_without_counting_a_failure(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """후보를 고른 뒤 선점 전에 되감기가 스냅샷을 지웠다 — 선점 INSERT 가 FK 에 걸리지만 경합이라 실패로 세지 않는다."""
    captured = _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)
    pick = memory_episodes._next_candidate

    async def _then_the_snapshot_is_rewound(*args: Any, **kwargs: Any) -> Any:
        candidate = await pick(*args, **kwargs)
        await db_session.execute(sa.delete(ChatRoomMemorySnapshot).where(ChatRoomMemorySnapshot.id == snapshot_id))
        await db_session.commit()
        return candidate

    monkeypatch.setattr(memory_episodes, "_next_candidate", _then_the_snapshot_is_rewound)
    fake = EpisodeLLMClient()

    await _extract(db_session, room, fake)

    assert fake.episode_prompts == []
    assert captured == []
    assert await _extractions(db_session, room) == []


@pytest.mark.parametrize(
    ("status", "minutes_ago", "attempts", "retaken"),
    [
        pytest.param("running", 11, 1, True, id="stale-running"),
        pytest.param("running", 11, 2, True, id="stale-running-second-attempt"),
        pytest.param("running", 11, 3, False, id="stale-running-at-the-attempt-limit"),
        pytest.param("running", 9, 1, False, id="fresh-running"),
        pytest.param("failed", 0, 2, True, id="failed-twice"),
        pytest.param("failed", 0, 3, False, id="failed-three-times"),
        pytest.param("done", 30, 1, False, id="done"),
    ],
)
async def test_stale_running_claim_is_retaken_within_attempt_limit(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    status: str,
    minutes_ago: int,
    attempts: int,
    retaken: bool,
) -> None:
    """작업이 죽어(배포 교체) `running` 이 남으면 10분 뒤 다음 작업이 다시 쥔다. 실패도 다시 쥔다. 어느 쪽이든 시도는 세 번까지다."""
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)
    db_session.add(
        _make_memory_extraction(
            room.room_id,
            snapshot_id,
            status=status,
            attempts=attempts,
            claimed_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            episode_count=1 if status == "done" else None,
        )
    )
    await db_session.commit()
    fake = EpisodeLLMClient()

    await _extract(db_session, room, fake)

    assert len(fake.episode_prompts) == (1 if retaken else 0)
    rows = await _extractions(db_session, room)
    if retaken:
        assert [(row.status, row.attempts) for row in rows] == [("done", attempts + 1)]
    else:
        assert [(row.status, row.attempts) for row in rows] == [(status, attempts)]


async def _supersede_claim(db_session: AsyncSession, snapshot_id: uuid.UUID) -> None:
    """다른 작업이 낡은 선점을 다시 쥔 상태 — 선점 시각이 새것으로 바뀌고 시도가 하나 늘었다."""
    await db_session.execute(
        sa.update(ChatMemoryExtraction)
        .where(ChatMemoryExtraction.snapshot_id == snapshot_id)
        .values(claimed_at=sa.func.clock_timestamp(), attempts=ChatMemoryExtraction.attempts + 1)
    )
    await db_session.commit()


async def test_late_finisher_with_superseded_claim_writes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """10분 넘게 걸린 작업이 그사이 다른 작업에 선점을 빼앗겼다 — 늦게 끝난 쪽은 아무것도 쓰지 않는다."""
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)

    async def _another_job_retakes_the_claim() -> MemoryEpisodeResult:
        await _supersede_claim(db_session, snapshot_id)
        return _result(_item())

    await _extract(db_session, room, EpisodeLLMClient(_another_job_retakes_the_claim))

    assert await _episodes(db_session, room) == []
    assert [(row.status, row.attempts, row.episode_count) for row in await _extractions(db_session, room)] == [
        ("running", 2, None)
    ]


async def test_a_failure_under_a_superseded_claim_leaves_the_new_claim_alone(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)

    async def _retaken_then_fails() -> MemoryEpisodeResult:
        await _supersede_claim(db_session, snapshot_id)
        raise LLMClientError("late")

    await _extract(db_session, room, EpisodeLLMClient(_retaken_then_fails))

    assert [(row.status, row.attempts) for row in await _extractions(db_session, room)] == [("running", 2)]


def test_production_env_leaves_extraction_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영 env 에는 추출 스위치·추출 모델 키가 없다 — 이 코드는 꺼진 채, 켜도 Gemini 로 배포된다."""
    assert not {"MEMORY_EPISODES_EXTRACT", "MEMORY_EPISODE_MODEL"} & set(PRODUCTION_ENV_NAMES)
    loaded = load_production_env(monkeypatch)
    assert (loaded.memory_episodes_extract, loaded.memory_episode_model) == (False, "gemini")
