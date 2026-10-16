"""장면·사실 기억 행을 Voyage 로 임베딩해 `chat_memory_embeddings` 에 채운다.

- Voyage 클라이언트: 임베딩 엔드포인트 하나를 `httpx` 로 부른다. 응답은 `index` 로 입력 순서에 맞추고, 개수·차원이 어긋나면
  실패다. 시간 초과·연결 실패·429·5xx 만 정해진 횟수까지 다시 보내고 그 밖의 4xx 는 바로 실패다. 응답을 받은 호출마다 그 토큰을
  일 단위 사용량 기록에 더한다(어드민 원가 화면이 읽는 곳).
- 설정: 쓰기 스위치(`memory_embed_write`)는 기본 꺼짐이고, 켜졌는데 Voyage 키가 비면 기동하지 않는다. 운영 env 에는 아직 이
  키들이 없어 꺼진 채 뜬다.
- 언제: 스위치가 켜져 있고 생성 윈도우가 켜져 있으면, 턴 뒤 접기·두 추출 예약 **뒤에** 채우기를 따로 예약한다. 꺼져 있으면
  예약하지 않아 Voyage 호출도, 임베딩 표 SELECT·INSERT 도 없다.
- 무엇을: 지금 모델·차원의 임베딩이 없는 장면·사실 행을, 방 단위로 스냅샷 커서 → 근거 원문 끝 키 → 장면 먼저 → 순번 순서로
  상한까지. 다음 채우기가 남은 행을 따라잡는다.
- 실패: 어떤 예외도 밖으로 내지 않는다(뒤 background 태스크가 돈다). 경고를 남기고 Bugsink 로 올린다. 그사이 되감긴 스냅샷의
  몫과 그사이 사라진 대상 행은 실패가 아니라 건너뛴다.

채우기 함수를 직접 부르는 테스트는 세션마다 SAVEPOINT 를 여는 팩토리를 쓴다(추출 테스트와 같은 이유). 진짜 두 세션의 경합(되감기와
겹침, 교착)은 `test_chat_memory_rewind.py` 의 커밋되는 독립 커넥션 절에 있다.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import BackgroundTasks
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_embeddings
from api.chat.memory_embeddings import EMBEDDING_CALL_SITE, fill_pending_embeddings
from api.chat.memory_rewind import rewind_memory
from api.chat.prompt_builder import (
    MemoryEpisodeResult,
    MemoryFactItem,
    MemoryFactResult,
    MemorySummaryResult,
    StatRuleJudgmentResult,
)
from api.core.config import Settings, settings
from api.core.rate_limit import KST
from api.db.models import ChatMemoryEmbedding, ChatMemoryEpisode, ChatMemoryFact, ChatRoomMemorySnapshot
from api.llm.client import LLMCallContext, LLMClient
from api.llm.dependencies import get_embedding_client
from api.llm.pricing import MODEL_PRICES, ModelPrice, estimate_cost_usd
from api.llm.usage_store import read_usage
from api.llm.voyage import TIMEOUT_SECONDS, VOYAGE_EMBEDDINGS_URL, EmbeddingError, VoyageEmbeddingClient
from api.main import app
from factories import (
    PRODUCTION_ENV_NAMES,
    Room,
    VoyageStub,
    _clear_llm_override,
    _make_memory_embedding,
    _make_memory_episode,
    _make_memory_fact,
    _open_room,
    _open_transaction_probe,
    _override_llm_client,
    _parse_sse_events,
    _plant_snapshot,
    load_production_env,
)

_MODEL = "voyage-test"


def _client(stub: VoyageStub, *, retry_delays: tuple[float, ...] = (0.0, 0.0)) -> VoyageEmbeddingClient:
    return VoyageEmbeddingClient(
        api_key="test-key", model=_MODEL, dims=stub.dims, transport=stub.transport(), retry_delays=retry_delays
    )


async def _embed(stub: VoyageStub, texts: list[str]) -> list[list[float]]:
    return await _client(stub).embed(texts, input_type="document", call_site=EMBEDDING_CALL_SITE)


# --- Voyage 클라이언트 -----------------------------------------------------------------------------


async def test_voyage_client_posts_documents_and_returns_vectors_in_input_order() -> None:
    """응답의 벡터 순서는 `index` 로만 입력과 맞는다 — 스텁은 순서를 뒤집어 돌려준다. 요청은 모델·출력 차원·문서 종류를 싣고
    키를 Bearer 로 보내며, 시간 상한을 건다."""
    stub = VoyageStub(dims=4)

    vectors = await _embed(stub, ["가", "나", "다"])

    assert vectors == [stub.vector(0), stub.vector(1), stub.vector(2)]
    request = stub.requests[0]
    assert (request.method, str(request.url)) == ("POST", VOYAGE_EMBEDDINGS_URL)
    assert request.headers["authorization"] == "Bearer test-key"
    assert stub.bodies == [
        {"input": ["가", "나", "다"], "model": _MODEL, "input_type": "document", "output_dimension": 4}
    ]
    assert request.extensions["timeout"]["read"] == TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(httpx.ReadTimeout("느림"), id="timeout"),
        pytest.param(httpx.ConnectError("끊김"), id="connect"),
        pytest.param(503, id="5xx"),
        pytest.param(429, id="rate-limit"),
    ],
)
async def test_voyage_client_retries_passing_failures_up_to_the_cap(failure: int | Exception) -> None:
    """지나가는 실패는 다시 보낸다 — 두 번 실패한 뒤 세 번째에 받으면 그 벡터다. 세 번 다 실패하면 거기서 멈춘다."""
    recovers = VoyageStub(failures=[failure, failure])
    assert await _embed(recovers, ["가"]) == [recovers.vector(0)]
    assert len(recovers.bodies) == 3

    keeps_failing = VoyageStub(failures=[failure] * 4)
    with pytest.raises(EmbeddingError):
        await _embed(keeps_failing, ["가"])
    assert len(keeps_failing.bodies) == 3


@pytest.mark.parametrize("status", [400, 401])
async def test_voyage_client_does_not_retry_a_request_it_rejected(status: int) -> None:
    """요청 자체가 틀렸거나 키가 틀린 실패는 다시 보내도 같다 — 한 번에 멈춘다."""
    stub = VoyageStub(failures=[status, status])

    with pytest.raises(EmbeddingError) as raised:
        await _embed(stub, ["가"])

    assert len(stub.bodies) == 1
    assert raised.value.status == status


def _answering(data: list[dict[str, Any]]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": data, "model": _MODEL, "usage": {"total_tokens": 3}})

    return handler


@pytest.mark.parametrize(
    "data",
    [
        pytest.param([{"embedding": [1.0, 0.5, 0.5], "index": 0}], id="fewer-vectors"),
        pytest.param(
            [{"embedding": [1.0, 0.5, 0.5], "index": 0}, {"embedding": [1.0, 0.5], "index": 1}], id="other-dims"
        ),
    ],
)
async def test_voyage_client_rejects_an_answer_that_does_not_match_the_inputs(data: list[dict[str, Any]]) -> None:
    """벡터가 입력보다 적거나 차원이 다르면 어느 행에 어느 벡터를 넣을지 모르거나 차원 CHECK 에 막힌다 — 넣기 전에 실패다."""
    client = VoyageEmbeddingClient(
        api_key="test-key", model=_MODEL, dims=3, transport=httpx.MockTransport(_answering(data)), retry_delays=()
    )

    with pytest.raises(EmbeddingError):
        await client.embed(["가", "나"], input_type="document", call_site=EMBEDDING_CALL_SITE)


async def test_each_answered_call_adds_its_tokens_to_the_usage_ledger() -> None:
    """Voyage 는 입력 토큰 합 하나(`usage.total_tokens`)만 보고한다 — 입력 토큰과 합계 둘 다에 그 값을 더해, 어드민 원가가
    입력 단가로 계산된다. 응답을 못 받은 시도는 세지 않는다."""
    stub = VoyageStub(failures=[503], total_tokens=42)

    await _embed(stub, ["가", "나"])

    today = datetime.now(KST).date()
    rows = await read_usage(today, today)
    assert [(row.call_site, row.model, row.calls, row.prompt, row.total, row.missing) for row in rows] == [
        (EMBEDDING_CALL_SITE, _MODEL, 1, 42, 42, 0)
    ]


def test_voyage_models_are_priced_as_input_only() -> None:
    """임베딩은 입력 토큰만 과금된다(Voyage 가격표, 100만 토큰당). 기본 모델에 단가가 없으면 어드민 원가가 "단가 없음"이 된다."""
    assert MODEL_PRICES["voyage-4-lite"] == ModelPrice(0.02, 0.0, 0.0)
    assert MODEL_PRICES["voyage-4"] == ModelPrice(0.06, 0.0, 0.0)
    assert MODEL_PRICES["voyage-4-large"] == ModelPrice(0.12, 0.0, 0.0)
    default = Settings.model_fields["memory_embed_model"].default
    assert estimate_cost_usd(
        default, input_tokens=1_000_000, cached_tokens=0, output_tokens=0, thoughts_tokens=0
    ) == pytest.approx(MODEL_PRICES[default].input_usd_per_million)


# --- 설정 ---------------------------------------------------------------------------------------


def test_embedding_write_without_a_voyage_key_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """키 없이 켜진 스위치는 채우기마다 실패할 뿐이라 켠 것이 성공한 것처럼 보인다 — 배포 단계에서 드러나게 기동을 막는다."""
    with pytest.raises(ValidationError, match="VOYAGE_API_KEY"):
        load_production_env(monkeypatch, MEMORY_EMBED_WRITE="true")
    with pytest.raises(ValidationError, match="VOYAGE_API_KEY"):
        load_production_env(monkeypatch, MEMORY_EMBED_WRITE="true", VOYAGE_API_KEY=" ")

    loaded = load_production_env(monkeypatch, MEMORY_EMBED_WRITE="true", VOYAGE_API_KEY="pa-test")

    assert (loaded.memory_embed_write, loaded.voyage_api_key) == (True, "pa-test")


def test_production_env_starts_with_embedding_off_and_no_voyage_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영 env 에는 임베딩 키가 하나도 없다 — 키 없음 기동 거부가 꺼진 스위치에는 걸리지 않아 그대로 뜬다."""
    assert not {"MEMORY_EMBED_WRITE", "MEMORY_EMBED_MODEL", "MEMORY_EMBED_DIMS", "VOYAGE_API_KEY"} & set(
        PRODUCTION_ENV_NAMES
    )

    loaded = load_production_env(monkeypatch)

    assert (loaded.memory_embed_write, loaded.voyage_api_key) == (False, "")
    assert (loaded.memory_embed_model, loaded.memory_embed_dims) == ("voyage-4-lite", 1024)


def test_embedding_model_and_dims_follow_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """모델·차원은 오프라인 비교 뒤 env 로 바꾼다 — 클라이언트는 요청마다 지금 설정으로 만든다."""
    loaded = load_production_env(monkeypatch, MEMORY_EMBED_MODEL="voyage-4", MEMORY_EMBED_DIMS="512")
    assert (loaded.memory_embed_model, loaded.memory_embed_dims) == ("voyage-4", 512)

    monkeypatch.setattr(settings, "memory_embed_model", "voyage-4")
    monkeypatch.setattr(settings, "memory_embed_dims", 512)
    client = get_embedding_client()

    assert (client.model, client.dims) == ("voyage-4", 512)


# --- 예약 ---------------------------------------------------------------------------------------


class _TurnLLMClient(LLMClient):
    """생성은 고정 응답, 요약은 고정 본문, 스탯 판정은 변화 없음, 장면 추출은 빈 결과, 사실 추출은 사실 하나."""

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
        assert response_schema is MemoryFactResult, response_schema
        return MemoryFactResult(
            facts=[
                MemoryFactItem(
                    kind="relation",
                    subject="민수",
                    object="지아",
                    attribute="",
                    value="소꿉친구",
                    truth_status="confirmed",
                    asserted_by="user",
                    speaker="",
                    known_by=[],
                    importance=3,
                    start_line=1,
                    end_line=2,
                )
            ]
        )


async def _send(db_client: httpx.AsyncClient, room: Room, stub: VoyageStub) -> list[str]:
    _override_llm_client(_TurnLLMClient())
    app.dependency_overrides[get_embedding_client] = lambda: _client(stub)
    try:
        response = await db_client.post(f"/chat-rooms/{room.room_id}/messages", json={"content": "새 메시지"})
    finally:
        _clear_llm_override()
        app.dependency_overrides.pop(get_embedding_client, None)
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


async def _embeddings(db_session: AsyncSession, room: Room) -> list[tuple[Any, ...]]:
    """(대상 종류, 대상 id, 모델, 차원, 벡터) — 대상 id 순."""
    rows = (
        await db_session.execute(
            sa.select(
                ChatMemoryEmbedding.episode_id,
                ChatMemoryEmbedding.fact_id,
                ChatMemoryEmbedding.model,
                ChatMemoryEmbedding.dims,
                ChatMemoryEmbedding.embedding,
            ).where(ChatMemoryEmbedding.chat_room_id == room.room_id)
        )
    ).all()
    return sorted(
        (
            ("episode", row.episode_id) if row.episode_id is not None else ("fact", row.fact_id),
            row.model,
            row.dims,
            row.embedding,
        )
        for row in rows
    )


async def test_embedding_fill_is_not_scheduled_when_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """꺼져 있으면 예약이 접기·추출뿐이다 — Voyage 를 부르지 않고 임베딩 표를 읽지도 쓰지도 않는다."""
    assert settings.memory_embed_write is False
    monkeypatch.setattr(settings, "memory_facts_extract", True)
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29)
    stub = VoyageStub()

    assert (await _send(db_client, room, stub))[-1] == "done"

    assert scheduled == ["fold_memory", "extract_pending_facts"]
    assert stub.bodies == []
    assert await _embeddings(db_session, room) == []


async def test_embedding_fill_runs_after_the_extractions_and_embeds_the_new_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """켜져 있으면 접기 → 장면 추출 → 사실 추출 뒤에 채우기가 예약되고, 같은 턴의 추출이 막 넣은 사실 행을 바로 임베딩한다.
    Voyage 를 기다리는 동안 DB 커넥션을 쥐지 않는다."""
    monkeypatch.setattr(settings, "memory_episodes_extract", True)
    monkeypatch.setattr(settings, "memory_facts_extract", True)
    monkeypatch.setattr(settings, "memory_embed_write", True)
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29)
    await db_session.commit()
    open_at_call: list[int] = []

    with _open_transaction_probe() as open_sessions:

        async def _record_open_sessions() -> None:
            open_at_call.append(len(open_sessions))

        stub = VoyageStub(before_answer=_record_open_sessions)
        events = await _send(db_client, room, stub)

    assert events[-1] == "done"
    assert scheduled == ["fold_memory", "extract_pending_episode", "extract_pending_facts", "fill_pending_embeddings"]
    assert stub.inputs == [["민수 → 지아: 소꿉친구"]]
    assert open_at_call == [0]
    fact_id = await db_session.scalar(sa.select(ChatMemoryFact.id).where(ChatMemoryFact.chat_room_id == room.room_id))
    assert await _embeddings(db_session, room) == [(("fact", fact_id), _MODEL, 3, stub.vector(0))]


async def test_embedding_fill_follows_the_generation_window_switch(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """생성 윈도우가 꺼져 있으면 접기가 없다 — 채우기 스위치가 켜져 있어도 예약하지 않는다."""
    monkeypatch.setattr(settings, "memory_embed_write", True)
    monkeypatch.setattr(settings, "memory_window_generation", False)
    scheduled = _record_scheduling(monkeypatch)
    room = await _open_room(db_client, db_session, turns=29)
    stub = VoyageStub()

    await _send(db_client, room, stub)

    assert scheduled == []
    assert stub.bodies == []


# --- 무엇을 채우는가 ------------------------------------------------------------------------------


def _savepoint_factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _fill(db_session: AsyncSession, room: Room, stub: VoyageStub) -> None:
    await fill_pending_embeddings(_savepoint_factory(db_session), _client(stub), room_id=room.room_id)


def _capture_failures(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    captured: list[str] = []
    monkeypatch.setattr(
        memory_embeddings, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    return captured


async def _plant(db_session: AsyncSession, room: Room, turn: int) -> uuid.UUID:
    await _plant_snapshot(db_session, room, turn=turn, text=f"[S{turn}]")
    assistant = room.turns[turn][1]
    snapshot_id = await db_session.scalar(
        sa.select(ChatRoomMemorySnapshot.id).where(
            ChatRoomMemorySnapshot.chat_room_id == room.room_id,
            ChatRoomMemorySnapshot.cursor_message_id == assistant.id,
        )
    )
    assert snapshot_id is not None
    return snapshot_id


def _source(room: Room, turn: int) -> dict[str, Any]:
    """근거 원문이 턴 `turn` 의 응답 한 메시지인 구간."""
    message = room.turns[turn][1]
    return {
        "start_created_at": message.created_at,
        "start_message_id": message.id,
        "end_created_at": message.created_at,
        "end_message_id": message.id,
        "start_turn": turn,
        "end_turn": turn,
    }


def _episode(room: Room, snapshot_id: uuid.UUID, *, turn: int, ordinal: int, title: str) -> ChatMemoryEpisode:
    return _make_memory_episode(
        room.room_id, snapshot_id, ordinal=ordinal, title=title, detail=f"{title} 본문", **_source(room, turn)
    )


def _fact(room: Room, snapshot_id: uuid.UUID, *, turn: int, ordinal: int, value: str) -> ChatMemoryFact:
    return _make_memory_fact(room.room_id, snapshot_id, ordinal=ordinal, value=value, **_source(room, turn))


async def test_fill_embeds_only_rows_without_an_embedding_of_the_current_model_and_dims(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이미 지금 모델·차원으로 임베딩한 행은 다시 보내지 않는다. 다른 모델이거나 같은 모델의 다른 차원으로만 임베딩된 행은
    지금 설정으로 새로 임베딩한다(그 행은 고쳐 쓰지 않고 새 행이 쌓인다). 장면 글은 제목과 본문을 줄바꿈으로 잇고, 사실 글은
    사실 섹션 한 줄의 본문(꼬리표 없음)이다."""
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)
    other_model = _episode(room, snapshot_id, turn=2, ordinal=0, title="다른 모델만")
    done = _fact(room, snapshot_id, turn=3, ordinal=0, value="이미 임베딩")
    other_dims = _make_memory_fact(
        room.room_id,
        snapshot_id,
        ordinal=1,
        kind="fact",
        object=None,
        attribute="성격",
        fact_key="fact|민수|성격",
        value="다정함",
        **_source(room, 4),
    )
    db_session.add_all([other_model, done, other_dims])
    await db_session.flush()
    db_session.add_all(
        [
            _make_memory_embedding(room.room_id, episode_id=other_model.id, model="other-model"),
            _make_memory_embedding(room.room_id, fact_id=done.id, model=_MODEL),
            _make_memory_embedding(room.room_id, fact_id=other_dims.id, model=_MODEL, dims=2, embedding=[0.5, 0.5]),
        ]
    )
    await db_session.commit()
    stub = VoyageStub()

    await _fill(db_session, room, stub)

    assert stub.inputs == [["다른 모델만\n다른 모델만 본문", "민수 · 성격: 다정함"]]
    current = [row for row in await _embeddings(db_session, room) if (row[1], row[2]) == (_MODEL, 3)]
    assert sorted(current) == sorted(
        [
            (("episode", other_model.id), _MODEL, 3, stub.vector(0)),
            (("fact", done.id), _MODEL, 3, [0.25, -0.5, 1.0]),
            (("fact", other_dims.id), _MODEL, 3, stub.vector(1)),
        ]
    )


async def test_fill_takes_the_oldest_rows_up_to_the_cap_and_catches_up_on_the_next_call(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """한 번에 상한까지만 보낸다. 오래된 순은 넣은 순서가 아니라 스냅샷 커서 → 근거 원문 끝 키 → 장면 먼저 → 순번이다 — 뒤
    스냅샷의 행을 먼저 넣고, 한 스냅샷 안에서는 순번과 원문 순서를 엇갈리게 두었다. 다음 채우기가 남은 행을 이어 받고, 남은
    행이 없으면 Voyage 를 부르지 않는다."""
    monkeypatch.setattr(memory_embeddings, "EMBED_BATCH_MAX", 3)
    room = await _open_room(db_client, db_session, turns=20)
    older = await _plant(db_session, room, 10)
    newer = await _plant(db_session, room, 20)
    db_session.add_all(
        [
            _fact(room, newer, turn=15, ordinal=0, value="뒤 스냅샷 사실"),
            _fact(room, older, turn=8, ordinal=0, value="앞 스냅샷 늦은 사실"),
            _fact(room, older, turn=3, ordinal=1, value="앞 스냅샷 이른 사실"),
            _episode(room, older, turn=8, ordinal=0, title="앞 스냅샷 늦은 장면"),
        ]
    )
    await db_session.commit()
    stub = VoyageStub()

    await _fill(db_session, room, stub)
    await _fill(db_session, room, stub)
    await _fill(db_session, room, stub)

    assert stub.inputs == [
        ["민수 → 지아: 앞 스냅샷 이른 사실", "앞 스냅샷 늦은 장면\n앞 스냅샷 늦은 장면 본문", "민수 → 지아: 앞 스냅샷 늦은 사실"],
        ["민수 → 지아: 뒤 스냅샷 사실"],
    ]
    assert len(await _embeddings(db_session, room)) == 4


async def test_a_scene_goes_before_a_fact_with_the_same_source_end_even_at_a_higher_ordinal(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """근거 원문의 끝 키가 같으면 장면이 사실보다 먼저다 — 순번은 그다음이라, 장면의 순번이 사실보다 커도 장면이 앞이다."""
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)
    db_session.add_all(
        [
            _fact(room, snapshot_id, turn=8, ordinal=0, value="같은 끝 사실"),
            _episode(room, snapshot_id, turn=8, ordinal=1, title="같은 끝 장면"),
        ]
    )
    await db_session.commit()
    stub = VoyageStub()

    await _fill(db_session, room, stub)

    assert stub.inputs == [["같은 끝 장면\n같은 끝 장면 본문", "민수 → 지아: 같은 끝 사실"]]


async def test_a_target_row_gone_before_the_insert_is_skipped_and_the_rest_are_inserted(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Voyage 를 기다리는 사이 대상 행 하나가 사라졌다. 그 행의 INSERT 만 외래 키(23503)에 걸리고, 같은 스냅샷의 다른 행은
    들어간다 — 행마다 SAVEPOINT 라 한 행의 위반이 트랜잭션 전체를 깨지 않는다. 사라진 행은 실패로 올리지 않는다."""
    captured = _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)
    first = _fact(room, snapshot_id, turn=2, ordinal=0, value="먼저")
    gone = _fact(room, snapshot_id, turn=3, ordinal=1, value="사라짐")
    last = _fact(room, snapshot_id, turn=4, ordinal=2, value="나중")
    db_session.add_all([first, gone, last])
    await db_session.commit()

    async def _the_row_disappears() -> None:
        await db_session.execute(sa.delete(ChatMemoryFact).where(ChatMemoryFact.id == gone.id))
        await db_session.commit()

    stub = VoyageStub(before_answer=_the_row_disappears)

    await _fill(db_session, room, stub)

    assert len(stub.inputs[0]) == 3
    assert captured == []
    assert await _embeddings(db_session, room) == sorted(
        [(("fact", first.id), _MODEL, 3, stub.vector(0)), (("fact", last.id), _MODEL, 3, stub.vector(2))]
    )


async def test_the_share_of_a_snapshot_rewound_during_the_call_is_skipped(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Voyage 를 기다리는 사이 뒤 스냅샷이 되감겼다. 그 스냅샷 몫은 넣지 않고(대상 행도 CASCADE 로 사라졌다) 남은 앞 스냅샷의
    몫은 넣는다. 되감김은 실패가 아니다."""
    captured = _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=20)
    older = await _plant(db_session, room, 10)
    newer = await _plant(db_session, room, 20)
    kept = _fact(room, older, turn=5, ordinal=0, value="남음")
    db_session.add_all([kept, _fact(room, newer, turn=15, ordinal=0, value="되감김")])
    await db_session.commit()

    async def _rewind_the_newer_snapshot() -> None:
        message = room.turns[15][0]
        await rewind_memory(db_session, room.room_id, (message.created_at, message.id))
        await db_session.commit()

    stub = VoyageStub(before_answer=_rewind_the_newer_snapshot)

    await _fill(db_session, room, stub)

    assert len(stub.inputs[0]) == 2
    assert captured == []
    assert await _embeddings(db_session, room) == [(("fact", kept.id), _MODEL, 3, stub.vector(0))]


# --- 예외를 밖으로 내지 않는다 ----------------------------------------------------------------------
#
# 채우기는 background 의 마지막 태스크지만, 뒤에 태스크가 더 붙어도 그 태스크가 돌아야 한다 — Starlette 는 태스크를 차례로 부르고
# 한 태스크가 예외를 내면 남은 태스크를 부르지 않는다.


@pytest.mark.parametrize(
    ("failures", "tag"),
    [
        pytest.param([503] * 3, "voyage", id="voyage-down"),
        pytest.param([429] * 3, "voyage_rate_limit", id="voyage-quota"),
        pytest.param([RuntimeError("예상하지 못한 오류")], "memory_embedding", id="unexpected"),
    ],
)
async def test_a_failed_fill_stays_inside_and_later_background_tasks_still_run(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    failures: list[int | Exception],
    tag: str,
) -> None:
    captured = _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)
    db_session.add(_fact(room, snapshot_id, turn=5, ordinal=0, value="값"))
    await db_session.commit()
    ran: list[str] = []

    async def _a_later_task() -> None:
        ran.append("later")

    tasks = BackgroundTasks()
    tasks.add_task(
        fill_pending_embeddings,
        _savepoint_factory(db_session),
        _client(VoyageStub(failures=failures)),
        room_id=room.room_id,
    )
    tasks.add_task(_a_later_task)
    await tasks()

    assert ran == ["later"]
    assert captured == [tag]
    assert await _embeddings(db_session, room) == []


async def test_a_database_error_in_the_insert_transaction_is_absorbed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """넣는 트랜잭션의 첫 문장이 DB 오류로 깨진다 — 함수는 그대로 돌아오고 `db` 로 올린다."""
    captured = _capture_failures(monkeypatch)
    room = await _open_room(db_client, db_session, turns=10)
    snapshot_id = await _plant(db_session, room, 10)
    db_session.add(_fact(room, snapshot_id, turn=5, ordinal=0, value="값"))
    await db_session.commit()

    async def _statement_fails(session: AsyncSession, *args: Any, **kwargs: Any) -> bool:
        await session.execute(sa.text("SELECT 1/0"))
        return True

    monkeypatch.setattr(memory_embeddings, "_lock_snapshot", _statement_fails)

    await _fill(db_session, room, VoyageStub())

    assert captured == ["db"]
    assert await _embeddings(db_session, room) == []

