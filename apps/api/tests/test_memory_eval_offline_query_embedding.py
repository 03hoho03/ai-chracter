"""궤적 재조립의 오프라인 질의 임베딩 — 임베딩 회상을 켠 갈래는 앱 조립 함수에 질의 벡터 파일에서 읽는 가짜 임베딩 클라이언트를
넘겨, 측정 서버처럼 명사·벡터 RRF 로 조립한다(클라이언트 없이 부르면 앱이 조용히 명사 단독으로 조립해 그 갈래를 틀리게 잰다).
외부 호출은 없다. 벡터 파일에 없는 질의 글이면 앱이 흡수하는 실패(명사 단독)로 떨어지지 않고 재조립을 멈춘다 — 빠진 글을 모으는
계획 모드에서만 멈추지 않고 글을 모은다. 임베딩 회상이 꺼진 갈래는 지금처럼 클라이언트 없이 조립한다."""

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
