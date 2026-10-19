"""넣기 절차의 임베딩 따라잡기·체크포인트 지문의 임베딩 칸·두 턴 프로브의 임베딩 미완 불능.

- 따라잡기는 운영 채우기 함수(`api.chat.memory_embeddings.fill_pending_embeddings`)를 넣기 자리에서 부르고, 그 클라이언트의
  모델·차원 임베딩이 없는 장면·사실 행 수와 있는 행 수를 앞뒤로 센다(연속 진전 없음 판정은 부르는 쪽이). 얼리기 직전에는 남은
  행이 없을 때까지 따라잡고, 정해진 횟수 안에 끝나지 않으면 얼리지 않는다.
- 지문은 임베딩 표가 있는 코드에서만 임베딩 행 수와 임베딩 없는 장면·사실 행 수를 싣는다.
- 임베딩 읽기를 켠 갈래의 두 턴 프로브는 둘째 턴 전 임베딩이 없는 행이 남아 있으면 불능이다 — 질의 쪽 벡터 순위가 첫 턴과
  다른 행 집합에서 나온다."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_embeddings
from api.db.models import ChatMemoryEmbedding, ChatRoomMemorySnapshot
from api.llm.voyage import VoyageEmbeddingClient
from factories import (
    Room,
    VoyageStub,
    _make_memory_embedding,
    _make_memory_episode,
    _make_memory_fact,
    _open_room,
    _plant_snapshot,
)
from memory_eval import checkpoint
from memory_eval import probe as probe_mod
from memory_eval.embed_catchup import EmbeddingCatchUp, finish_embeddings
from memory_eval.ledger import BudgetExceededError, Ledger
from memory_eval.probe import BurstPacer, ProbeRun, embedding_incomplete, memory_drift

MODEL = "voyage-test"


def _client(stub: VoyageStub) -> VoyageEmbeddingClient:
    return VoyageEmbeddingClient(
        api_key="test-key", model=MODEL, dims=stub.dims, transport=stub.transport(), retry_delays=(0.0, 0.0)
    )


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _room_with_memory(db_client: Any, db_session: AsyncSession) -> tuple[Room, list[uuid.UUID]]:
    """스냅샷 하나에 장면 둘·사실 하나. 첫 장면에는 다른 모델의 임베딩만 있다(지금 모델로는 없는 것과 같다)."""
    room = await _open_room(db_client, db_session, turns=2)
    await _plant_snapshot(db_session, room, turn=1, text="요약")
    snapshot_id = await db_session.scalar(
        sa.select(ChatRoomMemorySnapshot.id).where(ChatRoomMemorySnapshot.chat_room_id == room.room_id)
    )
    assert snapshot_id is not None
    first = _make_memory_episode(room.room_id, snapshot_id, ordinal=0)
    second = _make_memory_episode(room.room_id, snapshot_id, ordinal=1, title="두 번째 장면")
    fact = _make_memory_fact(room.room_id, snapshot_id)
    db_session.add_all([first, second, fact])
    await db_session.flush()
    db_session.add(_make_memory_embedding(room.room_id, episode_id=first.id, model="other-model", dims=3))
    await db_session.commit()
    return room, [first.id, second.id, fact.id]


# ---------------------------------------------------------------- 따라잡기


async def test_catch_up_fills_the_pending_rows_through_the_production_fill_and_counts_before_and_after(
    db_client: Any, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, _ = await _room_with_memory(db_client, db_session)
    called: list[uuid.UUID] = []
    real = memory_embeddings.fill_pending_embeddings

    async def spy(factory: Any, client: Any, *, room_id: uuid.UUID) -> None:
        called.append(room_id)
        await real(factory, client, room_id=room_id)

    monkeypatch.setattr(memory_embeddings, "fill_pending_embeddings", spy)
    stub = VoyageStub()
    catch_up = EmbeddingCatchUp(_client(stub))
    state = await catch_up.run_once(_factory(db_session), room.room_id)
    assert called == [room.room_id]
    assert state == {"model": MODEL, "dims": 3, "pendingBefore": 3, "doneBefore": 0, "doneAfter": 3}
    assert [body["input_type"] for body in stub.bodies] == ["document"]
    rows = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMemoryEmbedding).where(ChatMemoryEmbedding.model == MODEL)
    )
    assert rows == 3
    again = await catch_up.run_once(_factory(db_session), room.room_id)
    assert again == {"model": MODEL, "dims": 3, "pendingBefore": 0, "doneBefore": 3, "doneAfter": 3}
    assert len(stub.bodies) == 1  # 할 일이 없으면 Voyage 를 부르지 않는다


async def test_a_failed_fill_shows_as_no_progress(db_client: Any, db_session: AsyncSession) -> None:
    room, _ = await _room_with_memory(db_client, db_session)
    stub = VoyageStub(failures=[500, 500, 500])
    state = await EmbeddingCatchUp(_client(stub)).run_once(_factory(db_session), room.room_id)
    assert (state["pendingBefore"], state["doneBefore"], state["doneAfter"]) == (3, 0, 0)


def test_before_freezing_the_catch_up_repeats_until_nothing_is_pending_or_refuses() -> None:
    class Fake:
        def __init__(self, left: list[int]) -> None:
            self.left = left
            self.calls = 0

        async def run_once(self, factory: Any, room_id: uuid.UUID) -> dict[str, Any]:
            self.calls += 1
            before = self.left.pop(0)
            return {"pendingBefore": before, "doneBefore": 0, "doneAfter": 0}

        async def pending(self, factory: Any, room_id: uuid.UUID) -> int:
            return self.left[0]

    done = Fake([70, 6, 0])
    states = asyncio.run(finish_embeddings(done, None, uuid.uuid4(), attempts=3))  # type: ignore[arg-type]
    assert done.calls == 2 and [s["pendingBefore"] for s in states] == [70, 6]
    stuck = Fake([5, 5, 5, 5])
    with pytest.raises(SystemExit, match="임베딩"):
        asyncio.run(finish_embeddings(stuck, None, uuid.uuid4(), attempts=3))  # type: ignore[arg-type]
    assert stuck.calls == 3


# ---------------------------------------------------------------- 지문


async def test_fingerprint_carries_the_embedding_rows_and_the_rows_still_without_one(
    db_client: Any, db_session: AsyncSession
) -> None:
    room, (_first, _second, fact) = await _room_with_memory(db_client, db_session)
    db_session.add(_make_memory_embedding(room.room_id, fact_id=fact, model=MODEL, dims=3))
    await db_session.commit()
    conn = await db_session.connection()
    fingerprint = await checkpoint.compute_fingerprint(conn, room.room_id)
    # 임베딩 행은 둘(다른 모델 하나 포함), 어떤 임베딩도 없는 행은 둘째 장면 하나다.
    assert (fingerprint["embeddingCount"], fingerprint["unembeddedCount"]) == (2, 1)


# ---------------------------------------------------------------- 두 턴 프로브


_CP = {"cursor": ["2026-10-14T00:00:00", "m1"], "factCount": 3, "embeddingCount": 3, "unembeddedCount": 0}


def test_memory_guard_also_watches_the_embedding_rows() -> None:
    assert [d.split(":")[0] for d in memory_drift(_CP, {**_CP, "embeddingCount": 5})] == ["embeddingCount"]


def test_embedding_incomplete_only_for_arms_that_read_embeddings() -> None:
    now = {**_CP, "unembeddedCount": 2}
    assert embedding_incomplete(now, {"MEMORY_EMBED_RECALL": "true"}) == "임베딩 미완: 임베딩 없는 행 2개"
    assert embedding_incomplete(now, {"MEMORY_EMBED_RECALL": "false"}) is None
    assert embedding_incomplete(now, {}) is None
    assert embedding_incomplete(_CP, {"MEMORY_EMBED_RECALL": "true"}) is None
    old_code = {k: v for k, v in now.items() if k not in ("embeddingCount", "unembeddedCount")}
    assert embedding_incomplete(old_code, {"MEMORY_EMBED_RECALL": "true"}) is None


def _run(tmp_path: Path, overrides: dict[str, str]) -> ProbeRun:
    return ProbeRun(
        stage="s9", arm="b1-B2", room_id=uuid.uuid4(), run_dir=tmp_path, database_url="postgresql+asyncpg://x/lm_eval_w",
        cred_file=tmp_path / "c", cookie_file=tmp_path / "k", port=8130, server_overrides=overrides,
        allow_paid=False, opus_turn_usd=0.1, judgment_turn_usd=0.0, ledger=Ledger(tmp_path / "ledger.jsonl"),
        pacer=BurstPacer(limit=9, window_seconds=60.0),
    )  # fmt: skip


def test_guard_reports_embedding_incomplete_for_an_embedding_arm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """체크포인트 자체가 덜 채워진 채 얼려졌으면(지문이 같아 차이로는 안 잡힌다) 임베딩 읽기 갈래는 둘째 턴을 보내지 않는다."""
    incomplete = {**_CP, "embeddingCount": 2, "unembeddedCount": 1}

    async def read(url: str, room: uuid.UUID) -> dict[str, Any]:
        return dict(incomplete)

    monkeypatch.setattr(checkpoint, "read_fingerprint", read)
    monkeypatch.setattr(probe_mod, "MEMORY_GUARD_INTERVAL_SECONDS", 0.0)
    problems = probe_mod._guard_memory(_run(tmp_path, {"MEMORY_EMBED_RECALL": "true"}), incomplete)
    assert problems == ["임베딩 미완: 임베딩 없는 행 1개"]
    assert probe_mod.guard_reason(problems) == "둘째 턴 전 임베딩 미완"
    assert probe_mod._guard_memory(_run(tmp_path, {"MEMORY_EMBED_RECALL": "false"}), incomplete) == []
    assert probe_mod.guard_reason(["cursor: 체크포인트 a → 지금 b"]) == "둘째 턴 전 기억 상태가 체크포인트와 다르다"


# ---------------------------------------------------------------- 넣기 명령의 클라이언트


def test_fake_run_client_embeds_without_the_network_and_the_same_text_gets_the_same_vector() -> None:
    from memory_eval.embed_catchup import fake_embedding_client

    client = fake_embedding_client(model="voyage-4-lite", dims=8)
    vectors = asyncio.run(client.embed(["가", "나", "가"], input_type="document", call_site="t"))
    assert [len(v) for v in vectors] == [8, 8, 8]
    assert vectors[0] == vectors[2] != vectors[1]
    assert (client.model, client.dims) == ("voyage-4-lite", 8)


def test_paid_client_checks_the_ledger_headroom_and_writes_one_row_per_call(tmp_path: Path) -> None:
    from memory_eval.embed_catchup import LedgerVoyageClient

    stub = VoyageStub(total_tokens=11)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    client = LedgerVoyageClient(
        api_key="k", model="voyage-4-lite", dims=3, transport=stub.transport(), ledger=ledger, stage="s9-embed"
    )
    asyncio.run(client.embed(["가", "나"], input_type="document", call_site="chat_memory_embedding"))
    [row] = ledger.rows()
    assert (row["stage"], row["callSite"], row["model"], row["inputTokens"]) == (
        "s9-embed",
        "chat_memory_embedding",
        "voyage-4-lite",
        11,
    )
    broke = LedgerVoyageClient(
        api_key="k", model="voyage-4-lite", dims=3, transport=stub.transport(),
        ledger=Ledger(tmp_path / "capped.jsonl", cap_usd=0.0), stage="s9-embed",
    )  # fmt: skip
    with pytest.raises(BudgetExceededError):
        asyncio.run(broke.embed(["가"], input_type="document", call_site="chat_memory_embedding"))
    assert len(stub.bodies) == 1  # 상한에 걸린 호출은 보내지 않는다


async def test_a_budget_stop_inside_the_production_fill_is_not_swallowed(
    db_client: Any, db_session: AsyncSession, tmp_path: Path
) -> None:
    """운영 채우기는 어떤 예외도 삼킨다 — 원장 상한에 걸린 것까지 진전 없음으로 보이면 넣기가 세 턴을 더 돈다."""
    from memory_eval.embed_catchup import LedgerVoyageClient

    room, _ = await _room_with_memory(db_client, db_session)
    stub = VoyageStub()
    client = LedgerVoyageClient(
        api_key="k", model="voyage-4-lite", dims=3, transport=stub.transport(),
        ledger=Ledger(tmp_path / "capped.jsonl", cap_usd=0.0), stage="s9-embed",
    )  # fmt: skip
    with pytest.raises(BudgetExceededError):
        await EmbeddingCatchUp(client).run_once(_factory(db_session), room.room_id)
    assert stub.bodies == []


def test_insert_command_takes_the_embedding_fill_switch_with_model_and_dims(tmp_path: Path) -> None:
    from memory_eval_cli import build_parser

    argv = ["--run", str(tmp_path), "insert", "--plants", "p.json", "--fill-embeddings"]
    args = build_parser().parse_args([*argv, "--embed-model", "voyage-4-lite", "--embed-dims", "1024"])
    assert (args.fill_embeddings, args.embed_model, args.embed_dims) == (True, "voyage-4-lite", 1024)


# ---------------------------------------------------------------- 장면 내보내기의 벡터


async def test_episode_export_also_writes_the_stored_scene_vectors_in_the_offline_vector_file_form(
    db_client: Any, db_session: AsyncSession, tmp_path: Path
) -> None:
    """오프라인 회상이 템플릿 DB 에 저장된(반정밀도로 읽힌) 장면 벡터를 그대로 쓰게 — 같은 장면 글의 sha256 으로 찾히고, 사실
    임베딩은 싣지 않으며, 장면 하나에 모델·차원이 여럿이면 줄도 여럿이다."""
    from memory_eval import embed_offline as eo
    from memory_eval import recall_offline as ro
    from memory_eval.server_recall import export_episode_vectors, export_episodes

    room, (first, second, fact) = await _room_with_memory(db_client, db_session)
    db_session.add_all(
        [
            _make_memory_embedding(room.room_id, episode_id=second, model=MODEL, dims=3, embedding=[0.5, 0.25, -1.0]),
            _make_memory_embedding(room.room_id, fact_id=fact, model=MODEL, dims=3),
        ]
    )
    await db_session.commit()
    rows = await export_episode_vectors(db_session, room.room_id)
    assert sorted((r["model"], r["inputType"]) for r in rows) == [("other-model", "document"), (MODEL, "document")]
    exported = tmp_path / "episodes.json"
    exported.write_text(json.dumps(await export_episodes(db_session, room.room_id), default=str), encoding="utf-8")
    episodes = {e.id: e for e in ro.load_episodes_json(exported)}
    table = eo.EmbeddingTable.from_rows(rows, model=MODEL, dims=3)
    assert table.vector("document", eo.episode_text(episodes[str(second)])) == [0.5, 0.25, -1.0]
    assert not table.has("document", eo.episode_text(episodes[str(first)]))
