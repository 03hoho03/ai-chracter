"""궤적 재조립의 오프라인 질의 임베딩 — 임베딩 회상을 켠 갈래는 앱 조립 함수에 질의 벡터 파일에서 읽는 가짜 임베딩 클라이언트를
넘겨, 측정 서버처럼 명사·벡터 RRF 로 조립한다(클라이언트 없이 부르면 앱이 조용히 명사 단독으로 조립해 그 갈래를 틀리게 잰다).
외부 호출은 없다. 벡터 파일에 없는 질의 글이면 앱이 흡수하는 실패(명사 단독)로 떨어지지 않고 재조립을 멈춘다 — 빠진 글을 모으는
계획 모드에서만 멈추지 않고 글을 모은다. 임베딩 회상이 꺼진 갈래는 지금처럼 클라이언트 없이 조립한다."""

import json
import uuid
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_nouns import episode_nouns
from api.chat.memory_vector import embed_query, query_text
from api.chat.prompt_builder import load_active_prompt_set
from api.chat.router import _resolve_starting_setup
from api.chat.turn_prompt import GenerationPrompt, build_room_prompt
from api.core.config import settings
from api.db.models import ChatMessage, ChatRoom, ChatRoomMemorySnapshot
from api.llm.chat_models import ChatModelId
from factories import _make_memory_embedding, _make_memory_episode, _memory_scope_covers_gemini, _open_room
from memory_eval import embed_offline as eo
from memory_eval import offline_embedding as oe

MODEL, DIMS = "voyage-offline-test", 3
_NEAR = [1.0, 0.5, 0.5]
_FAR = [0.0, 1.0, -1.0]


def _table(texts: dict[str, list[float]]) -> eo.EmbeddingTable:
    rows = [
        {"model": MODEL, "dims": DIMS, "inputType": "query", "sha256": eo.text_sha(t), "vector": v}
        for t, v in texts.items()
    ]
    return eo.EmbeddingTable.from_rows(rows, model=MODEL, dims=DIMS)


def test_only_arms_that_turn_on_embedding_recall_get_a_client_and_they_refuse_without_vectors() -> None:
    table = _table({})
    for arm in ("b1-B2", "b1-B1E"):
        client = oe.client_for(arm, table)
        assert client is not None and (client.model, client.dims) == (MODEL, DIMS), arm
        with pytest.raises(SystemExit, match=arm):
            oe.client_for(arm, None)
    # 꺼진 갈래(자기 재렌더 포함)는 벡터 파일이 있어도 없어도 클라이언트 없이 — 지금 조립 그대로다.
    for arm in ("baseline", "A2", "B2", "b1-A0", "b1-A1", "b1-B1", "b1-B2-bare", "b1-B1E-bare"):
        assert oe.client_for(arm, table) is None, arm
        assert oe.client_for(arm, None) is None, arm
    assert oe.embedding_arms(["b1-A1", "b1-B2", "b1-B2-bare", "b1-B1E"]) == ["b1-B2", "b1-B1E"]


async def test_client_reads_the_query_vector_by_the_text_hash_and_never_answers_documents() -> None:
    text = query_text("정원 생각나?", "직전 응답")
    client = oe.OfflineQueryEmbeddingClient(_table({text: _NEAR}))
    assert await client.embed_with_usage([text], input_type="query", call_site="x") == ([_NEAR], 0)
    assert await client.embed([text], input_type="query", call_site="x") == [_NEAR]
    with pytest.raises(SystemExit, match="document"):
        await client.embed([text], input_type="document", call_site="x")


async def test_missing_query_vector_stops_through_the_apps_failure_absorption() -> None:
    """앱의 질의 임베딩은 실패를 흡수해 명사 단독으로 간다 — 가짜의 멈춤은 그 흡수에 먹히지 않아야 한다."""
    client = oe.OfflineQueryEmbeddingClient(_table({}))
    with pytest.raises(SystemExit, match="질의 벡터"):
        await embed_query(client, "벡터 없는 글", timeout_seconds=5.0, room_id=uuid.uuid4())


async def test_plan_mode_collects_missing_query_texts_in_the_embed_plan_shape_without_stopping() -> None:
    missing: list[dict[str, str]] = []
    client = oe.OfflineQueryEmbeddingClient(_table({"있는 글": _NEAR}), missing=missing)
    for text in ("빠진 글", "있는 글", "빠진 글"):
        result = await embed_query(client, text, timeout_seconds=5.0, room_id=uuid.uuid4())
        assert (result.vector is not None) == (text == "있는 글")
    assert missing == [{"inputType": "query", "sha256": eo.text_sha("빠진 글"), "text": "빠진 글"}]


async def _room_with_scenes(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[ChatRoom, list[uuid.UUID]]:
    """8턴 스토리 방, 턴 6 응답까지 접힌 스냅샷 하나, 장면 여섯(명사가 방 메시지와 겹치지 않는다)과 그 임베딩."""
    room = await _open_room(db_client, db_session, turns=8, lane="story")
    assistant = room.turns[6][1]
    snapshot = ChatRoomMemorySnapshot(
        chat_room_id=room.room_id,
        cursor_created_at=assistant.created_at,
        cursor_message_id=assistant.id,
        summary_text="턴 6 까지의 요약",
        source="auto",
    )
    db_session.add(snapshot)
    await db_session.flush()
    ids = []
    for i in range(6):
        user, reply = room.turns[i + 1]
        title, detail = f"장면 {i}", f"평범한 하루 {i}번째."
        episode = _make_memory_episode(
            room.room_id, snapshot.id, ordinal=i, start_created_at=user.created_at, start_message_id=user.id,
            end_created_at=reply.created_at, end_message_id=reply.id, start_turn=i + 1, end_turn=i + 1,
            title=title, detail=detail, nouns=episode_nouns([f"일상{i}"], title, detail),
        )  # fmt: skip
        db_session.add(episode)
        await db_session.flush()
        ids.append(episode.id)
        db_session.add(
            _make_memory_embedding(
                room.room_id, episode_id=episode.id, model=MODEL, dims=DIMS, embedding=_NEAR if i == 2 else _FAR
            )
        )
    await db_session.commit()
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    return chat_room, ids


async def test_app_assembly_with_the_offline_client_recalls_the_vector_neighbour_or_stops(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, ids = await _room_with_scenes(db_client, db_session)
    monkeypatch.setattr(settings, "memory_episodes_recall", True)
    monkeypatch.setattr(settings, "memory_embed_recall", True)
    # 이 테스트는 Gemini 세트로 조립하는데 기억 사용 범위의 기본값은 Opus 방뿐이다 — 범위를 넓히지 않으면 회상과 질의 임베딩이
    # 둘 다 꺼진 채 조립돼 빈 회상을 본다.
    _memory_scope_covers_gemini(monkeypatch)
    setup = await _resolve_starting_setup(db_session, room)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    history = list(
        (
            await db_session.scalars(
                sa.select(ChatMessage)
                .where(ChatMessage.chat_room_id == room.id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
    )
    user_text = "오늘 날씨 좋다"
    # 질의 글은 운영 질의 글 함수의 꼴(이번 사용자 메시지 + 줄바꿈 + 직전 응답)이고 그 글의 해시로 벡터를 찾는다.
    text = query_text(user_text, history[-1].content)

    async def build(table: eo.EmbeddingTable) -> GenerationPrompt:
        return await build_room_prompt(
            db_session, room, setup, history, user_text, None, prompt_set, sections,
            embedding_client=oe.OfflineQueryEmbeddingClient(table),
        )  # fmt: skip

    built = await build(_table({text: _NEAR}))
    assert [entry["episodeId"] for entry in built.memory_recall] == [str(ids[2])]
    assert built.memory_query is not None and built.memory_query["outcome"] == "ok"
    with pytest.raises(SystemExit, match="질의 벡터"):
        await build(_table({"다른 글": _NEAR}))


def _replay_args(tmp_path: Path, arms: str, *extra: str) -> list[str]:
    return [
        "--run", str(tmp_path), "trajectory-replay", "--room", str(uuid.uuid4()),
        "--insert-log", str(tmp_path / "no-insert-log.jsonl"), "--arms", arms, "--out-dir", str(tmp_path / "out"),
        # B 계열 갈래(B1E)는 템플릿 이름이 있어야 계열 거부를 지난다.
        "--label", "b1-measure", "--checkpoint", "300", *extra,
    ]  # fmt: skip


def test_trajectory_replay_refuses_an_embedding_arm_without_a_vector_file_before_reading_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    assert main(_replay_args(tmp_path, "b1-A1,b1-B1E")) == 2
    err = capsys.readouterr().err
    assert "b1-B1E" in err and "--embeddings" in err
    vectors = tmp_path / "vectors.jsonl"
    vectors.write_text("", encoding="utf-8")
    # 벡터 파일·모델·차원을 주면 이 거부를 지나 넣기 기록을 읽으러 간다.
    with pytest.raises(FileNotFoundError):
        main(
            _replay_args(tmp_path, "b1-B1E", "--embeddings", str(vectors), "--embed-model", MODEL, "--embed-dims", "3")
        )
    # 임베딩 회상이 꺼진 갈래만이면 벡터 파일 없이도 그대로 간다.
    with pytest.raises(FileNotFoundError):
        main(_replay_args(tmp_path, "b1-A1,b1-B1"))


def test_trajectory_point_refuses_an_embedding_arm_without_a_vector_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    args = ["--run", str(tmp_path), "trajectory", "--room", str(uuid.uuid4()), "--next-turn", "2",
            "--user-text", "안녕", "--arms", "b1-B2"]  # fmt: skip
    assert main(args) == 2
    err = capsys.readouterr().err
    assert "b1-B2" in err and "--embeddings" in err


async def test_trajectory_point_records_the_query_outcome_and_a_room_out_of_memory_scope_stops(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """단독 궤적 점도 질의 임베딩 결과를 적는다. 기억 사용 범위 밖 방은 임베딩 회상 갈래라도 질의 임베딩을 부르지 않아 명사
    단독으로 조립되므로, 재조립과 같은 단언이 그 점을 거부해야 한다. 갈래 설정이 범위를 측정 서버 값(두 레인의 Opus)으로
    씌우므로 테스트에서 범위를 넓혀도 덮인다 — 범위 안은 실제 측정처럼 Opus 세트, 범위 밖은 Gemini 세트로 조립한다."""
    from memory_eval.trajectory import assemble_point
    from memory_eval.trajectory_replay import require_query_embedded

    room, ids = await _room_with_scenes(db_client, db_session)
    history = list(
        (
            await db_session.scalars(
                sa.select(ChatMessage)
                .where(ChatMessage.chat_room_id == room.id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
    )
    user_text = "오늘 날씨 좋다"
    table = _table({query_text(user_text, history[-1].content): _NEAR})

    async def point(model: ChatModelId) -> dict[str, object]:
        built, _ = await assemble_point(
            db_session, room.id, next_turn=9, user_content=user_text, arm="b1-B1E", model=model,
            recall_field="memory_recall", embeddings=table,
        )  # fmt: skip
        return built

    inside = await point("opus")
    assert (inside["queryOutcome"], inside["snapshotsSeen"]) == ("ok", 1)
    assert [entry["episodeId"] for entry in inside["recall"]] == [str(ids[2])]  # type: ignore[attr-defined]
    assert require_query_embedded([inside]) == {"expected": 1, "ok": 1}

    outside = await point("gemini")
    assert (outside["queryOutcome"], outside["snapshotsSeen"]) == (None, 1)
    with pytest.raises(SystemExit, match="질의 임베딩"):
        require_query_embedded([outside])


def test_trajectory_command_writes_no_point_whose_query_embedding_is_not_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval import runtime, trajectory
    from memory_eval_cli import main

    async def unembedded(*_: object, arm: str, next_turn: int, **__: object) -> tuple[dict[str, object], str]:
        return {"turn": next_turn, "arm": arm, "queryOutcome": None, "snapshotsSeen": 1}, ""

    monkeypatch.setattr(runtime, "work_database_url", lambda *, writes: "postgresql+asyncpg://x@localhost/lm_eval_work")
    monkeypatch.setattr(trajectory, "assemble_point", unembedded)
    vectors = tmp_path / "vectors.jsonl"
    vectors.write_text("", encoding="utf-8")
    args = ["--run", str(tmp_path), "trajectory", "--room", str(uuid.uuid4()), "--next-turn", "9",
            "--user-text", "안녕", "--arms", "b1-B2", "--embeddings", str(vectors),
            "--embed-model", MODEL, "--embed-dims", "3"]  # fmt: skip
    assert main(args) == 2
    assert "질의 임베딩" in capsys.readouterr().err
    assert not list(tmp_path.glob("trajectory-*.jsonl"))


def _fake_replay_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, replay_point: object) -> Path:
    """재조립 명령의 DB·템플릿 지문을 가짜로 지나게 하고 조립된 점만 `replay_point` 로 꾸민다. 벡터 파일(빈 것) 경로를 돌려준다."""
    from types import SimpleNamespace

    from memory_eval import checkpoint, runtime, trajectory_replay as tr
    from memory_eval.arm_env import series_label

    class FakeDb:
        async def connection(self) -> object:
            return object()

    class FakeSession:
        async def __aenter__(self) -> FakeDb:
            return FakeDb()

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeEngine:
        async def dispose(self) -> None:
            return None

    async def nothing(*_: object, **__: object) -> None:
        return None

    async def fingerprint(*_: object, **__: object) -> dict[str, object]:
        return {}

    async def story_room(*_: object, **__: object) -> SimpleNamespace:
        return SimpleNamespace(lane="story")

    async def prompt_set(*_: object, **__: object) -> tuple[None, list[object]]:
        return None, []

    monkeypatch.setattr(runtime, "work_database_url", lambda *, writes: "postgresql+asyncpg://x@localhost/lm_eval_work")
    monkeypatch.setattr(runtime, "make_engine", lambda _url: (FakeEngine(), FakeSession))
    monkeypatch.setattr(runtime, "load_room", story_room)
    monkeypatch.setattr(runtime, "generation_set", prompt_set)
    monkeypatch.setattr(checkpoint, "compute_fingerprint", fingerprint)
    monkeypatch.setattr(checkpoint, "compute_summary_digest", nothing)
    monkeypatch.setattr(tr, "check_template", lambda *_a, **_k: None)
    monkeypatch.setattr(tr, "load_timeline", nothing)
    monkeypatch.setattr(tr, "injected_persona", nothing)
    monkeypatch.setattr(tr, "section_header", lambda *_a: "[머리글]")
    monkeypatch.setattr(tr, "replay_point", replay_point)
    fingerprint_file = tmp_path / "dumps" / f"{series_label('b1-measure', 'b1-B1E')}-cp300.fingerprint.json"
    fingerprint_file.parent.mkdir(parents=True)
    fingerprint_file.write_text("{}", encoding="utf-8")
    (tmp_path / "no-insert-log.jsonl").write_text("", encoding="utf-8")
    vectors = tmp_path / "vectors.jsonl"
    vectors.write_text("", encoding="utf-8")
    return vectors


def test_trajectory_replay_command_writes_no_file_when_a_query_embedding_is_not_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """재조립 명령도 임베딩 회상 갈래의 점 하나라도 질의 임베딩이 `ok` 가 아니면 궤적 파일을 하나도 쓰지 않고 비0 으로 끝난다 —
    단언 함수만 보는 테스트로는 명령이 그 단언을 부르는지 알 수 없다. DB·템플릿 지문은 가짜로 지나고 조립된 점만 꾸민다."""
    from memory_eval_cli import main

    async def unembedded(*_: object, turn: int, arm: str, **__: object) -> tuple[dict[str, object], str]:
        point = {"turn": turn, "arm": arm, "queryOutcome": None, "snapshotsSeen": 1, "segmentSha": ["a", "b"]}
        return point, ""

    vectors = _fake_replay_env(monkeypatch, tmp_path, unembedded)
    args = _replay_args(
        tmp_path, "b1-B1E", "--turns", "2,3", "--embeddings", str(vectors), "--embed-model", MODEL, "--embed-dims", "3"
    )
    assert main(args) == 2
    assert "질의 임베딩" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


async def _app_query_step(
    embeddings: eo.EmbeddingTable | None, missing: list[dict[str, str]] | None, text: str
) -> None:
    """앱 조립이 질의 임베딩 앞뒤로 하는 일만 — Voyage 멈춤 상태를 묻고, 허락되면 질의 임베딩을 받는다(실패는 연속 실패로 센다)."""
    from api.chat.voyage_backoff import voyage_allowed

    client = oe.client_for("b1-B1E", embeddings, missing=missing)
    assert client is not None
    if await voyage_allowed():
        await embed_query(client, text, timeout_seconds=5.0, room_id=uuid.uuid4())


def test_plan_mode_collects_every_missing_query_and_leaves_the_voyage_backoff_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """계획 모드의 빠진 질의는 Voyage 장애가 아니다 — 앱이 그것을 연속 실패로 세면 세 번째에 전역 멈춤 키가 서고, 그 뒤 턴은
    질의 임베딩을 부르지 않아 빠진 글이 세 개에서 멈춘다. 다섯 턴이면 다섯 글을 모두 모으고, 멈춤 키를 남기지 않아야 한다."""
    import redis
    from redis.asyncio import Redis

    from api.chat import voyage_backoff
    from memory_eval_cli import main

    # 명령은 자기 이벤트 루프를 새로 돌리므로 다른 루프에서 연결이 붙은 공용 클라이언트 대신 새 클라이언트를 준다.
    monkeypatch.setattr(voyage_backoff, "redis_client", Redis.from_url(settings.redis_url, decode_responses=True))
    state = redis.Redis.from_url(settings.redis_url)

    async def app_like(
        *_: object,
        turn: int,
        arm: str,
        embeddings: eo.EmbeddingTable | None,
        missing: list[dict[str, str]] | None,
        **__: object,
    ) -> tuple[dict[str, object], str]:
        await _app_query_step(embeddings, missing, f"빠진 질의 {turn}")
        return {"turn": turn, "arm": arm, "queryOutcome": "failed", "snapshotsSeen": 1, "segmentSha": ["a", "b"]}, ""

    vectors = _fake_replay_env(monkeypatch, tmp_path, app_like)
    plan = tmp_path / "plan.jsonl"
    args = _replay_args(
        tmp_path, "b1-B1E", "--turns", "2,6", "--embeddings", str(vectors), "--embed-model", MODEL, "--embed-dims", "3",
        "--embed-plan-out", str(plan),
    )  # fmt: skip
    assert main(args) == 0
    assert [json.loads(line)["text"] for line in plan.read_text(encoding="utf-8").splitlines()] == [
        f"빠진 질의 {t}" for t in range(2, 7)
    ]
    assert state.exists(voyage_backoff.VOYAGE_BACKOFF_KEY) == 0


def test_trajectory_replay_writes_the_summary_json_to_its_own_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """검사 줄이 읽는 요약 JSON 은 화면 출력과 따로 파일로도 남는다 — 화면은 경고 줄과 섞여 JSON 으로 읽히지 않을 수 있다."""
    from redis.asyncio import Redis

    from api.chat import voyage_backoff
    from memory_eval_cli import main

    monkeypatch.setattr(voyage_backoff, "redis_client", Redis.from_url(settings.redis_url, decode_responses=True))

    async def app_like(
        *_: object,
        turn: int,
        arm: str,
        embeddings: eo.EmbeddingTable | None,
        missing: list[dict[str, str]] | None,
        **__: object,
    ) -> tuple[dict[str, object], str]:
        await _app_query_step(embeddings, missing, f"빠진 질의 {turn}")
        return {"turn": turn, "arm": arm, "queryOutcome": "failed", "snapshotsSeen": 1, "segmentSha": ["a", "b"]}, ""

    vectors = _fake_replay_env(monkeypatch, tmp_path, app_like)
    summary = tmp_path / "summary" / "plan.json"
    args = _replay_args(
        tmp_path, "b1-B1E", "--turns", "2,3", "--embeddings", str(vectors), "--embed-model", MODEL, "--embed-dims", "3",
        "--embed-plan-out", str(tmp_path / "plan.jsonl"), "--summary-out", str(summary),
    )  # fmt: skip
    assert main(args) == 0
    written = json.loads(summary.read_text(encoding="utf-8"))
    assert written == {"embedPlan": str(tmp_path / "plan.jsonl"), "missingQueries": 2, "trajectoryWritten": False}
    assert json.loads(capsys.readouterr().out) == written


def test_full_replay_keeps_the_apps_voyage_backoff_and_writes_no_summary_file_unasked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """계획 모드가 아닌 본 재조립은 앱의 Voyage 백오프 자리를 그대로 둔다 — 실제 Redis 에 남은 멈춤 키를 그대로 존중해야
    질의 임베딩이 빠진 궤적을 `require_query_embedded` 가 잡는다. `--summary-out` 을 주지 않으면 요약 파일도 만들지 않는다."""
    from api.chat import voyage_backoff
    from memory_eval_cli import main

    original = object()
    monkeypatch.setattr(voyage_backoff, "redis_client", original)
    seen: list[bool] = []

    async def embedded(*_: object, turn: int, arm: str, **__: object) -> tuple[dict[str, object], str]:
        seen.append(vars(voyage_backoff)["redis_client"] is original)
        return {"turn": turn, "arm": arm, "queryOutcome": "ok", "snapshotsSeen": 1, "segmentSha": ["a", "b"]}, ""

    vectors = _fake_replay_env(monkeypatch, tmp_path, embedded)
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    args = _replay_args(
        tmp_path, "b1-B1E", "--turns", "2,3", "--embeddings", str(vectors), "--embed-model", MODEL, "--embed-dims", "3"
    )
    assert main(args) == 0
    assert seen and all(seen)
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()} - {
        p.relative_to(tmp_path).as_posix() for p in before
    }
    assert written == {"out/trajectory-b1-B1E.jsonl", "out/trajectory-b1-B1E-bare.jsonl"}


def test_plan_mode_backoff_off_puts_the_apps_redis_slot_back_after_the_block_and_after_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """빈 상태는 블록 안에서만 앱 모듈 자리에 있다 — 블록이 끝나거나 블록 안에서 예외가 나도 원래 객체로 돌아와야 한 프로세스의
    다음 일(본 재조립)이 실제 백오프 상태를 본다. 테스트 끝의 자동 복원에 가려지지 않게 블록 직후에 본다."""
    from api.chat import voyage_backoff

    original = object()
    monkeypatch.setattr(voyage_backoff, "redis_client", original)
    with oe.plan_mode_backoff_off():
        assert vars(voyage_backoff)["redis_client"] is not original
    assert vars(voyage_backoff)["redis_client"] is original

    with pytest.raises(RuntimeError, match="블록 안 실패"), oe.plan_mode_backoff_off():
        raise RuntimeError("블록 안 실패")
    assert vars(voyage_backoff)["redis_client"] is original


def test_replay_applies_the_given_hybrid_settings_and_restores_them() -> None:
    """재조립 프로세스의 하이브리드 설정은 `.env` 가 아니라 실행 인자(측정 서버에 준 값)로 정한다 — df 상한 '없음'도."""
    saved = {name: getattr(settings, name) for name in eo.CONFIG_NAMES}
    params = eo.HybridParams(rrf_k=7, max_plain=2, max_cue=5, max_distance=0.4, vector_limit=3, df_max=None)
    settings.memory_embed_recall_df_max = 99
    try:
        with oe.recall_settings(params):
            assert {name: getattr(settings, name) for name in eo.CONFIG_NAMES} == params.config()
        assert settings.memory_embed_recall_df_max == 99
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


async def test_replay_point_hands_the_offline_client_only_to_embedding_arms(monkeypatch: pytest.MonkeyPatch) -> None:
    """재조립의 한 점이 앱 조립 함수에 넘기는 클라이언트 — 임베딩 회상 갈래만 오프라인 클라이언트, 꺼진 갈래는 None."""
    from types import SimpleNamespace

    from api.chat.prompt_builder import PromptNames
    from api.db.models import ChatMessageRole
    from memory_eval import trajectory_replay as tr

    seen: list[object] = []

    async def fake_build(*_args: object, embedding_client: object = None, **_kw: object) -> object:
        seen.append(embedding_client)
        return SimpleNamespace(
            prompt="p", memory_recall=(), memory_facts=(), memory_query=None, names=PromptNames(None, None)
        )

    class FakeDb:
        async def scalars(self, _statement: object) -> object:
            return SimpleNamespace(all=list)

    monkeypatch.setattr(tr, "build_room_prompt", fake_build)
    messages = [
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="오프닝"),
        ChatMessage(role=ChatMessageRole.USER, content="안녕"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="응"),
    ]
    timeline = tr.RoomTimeline(messages=messages, user_indices=[1], snapshots=[])
    ctx = SimpleNamespace(room=SimpleNamespace(id=uuid.uuid4(), content_version_id=uuid.uuid4()), setup=None)

    async def point(arm: str, table: eo.EmbeddingTable | None) -> None:
        await tr.replay_point(
            FakeDb(), ctx, timeline, turn=1, counts={}, arm=arm, prompt_set=(None, []), persona=None,  # type: ignore[arg-type]
            recall_header="[회상]", fact_header="[사실]", embeddings=table,
        )  # fmt: skip

    table = _table({})
    await point("b1-B1E", table)
    await point("b1-B1", table)
    assert isinstance(seen[0], oe.OfflineQueryEmbeddingClient) and seen[1] is None
    with pytest.raises(SystemExit, match="b1-B2"):
        await point("b1-B2", None)
