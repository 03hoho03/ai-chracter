"""두 템플릿 계열 — 요약 표기가 켜진 B 계열 템플릿은 A 계열 템플릿을 복제해 그 방 스냅샷의 요약 글만 바꾼다. 장면·사실 행은
그대로라 두 계열의 차이는 요약 글뿐이다. 방의 스냅샷 하나라도 B 판 요약이 없으면 아무것도 바꾸지 않고 거부하고(일부만 바뀐
템플릿은 두 계열이 섞인 상태다), 바꾼 뒤 지문이 A 계열 지문과 다르면 그 템플릿을 지우고 거부한다. 다시 만들 때 요약을 못
바꾸면 A 복제본이 된 B 템플릿과 옛 B 산출물을 함께 지운다. B 지문에는 요약 글 해시가 들어 있어, 복원 때 템플릿의 요약이
B 판이 아니면 거부한다."""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import ChatRoomMemorySnapshot
from factories import _open_room, _plant_snapshot
from memory_eval import checkpoint as checkpoint_mod
from memory_eval import series_template as st
from memory_eval.arm_env import B_SERIES_SUFFIX, series_label


async def _snapshots(db_session: AsyncSession, room_id: uuid.UUID) -> list[ChatRoomMemorySnapshot]:
    rows = await db_session.scalars(
        sa.select(ChatRoomMemorySnapshot)
        .where(ChatRoomMemorySnapshot.chat_room_id == room_id)
        .order_by(ChatRoomMemorySnapshot.cursor_created_at)
    )
    return list(rows)


async def test_rewrite_replaces_only_summary_text_of_every_room_snapshot(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=4)
    other = await _open_room(db_client, db_session, turns=2)
    await _plant_snapshot(db_session, room, turn=1, text="A 요약 1")
    await _plant_snapshot(db_session, room, turn=3, text="A 요약 2")
    await _plant_snapshot(db_session, other, turn=1, text="다른 방 요약")
    first, second = await _snapshots(db_session, room.room_id)
    summaries = {str(first.id): "B 요약 1", str(second.id): "B 요약 2", str(uuid.uuid4()): "뒤 체크포인트의 요약"}

    conn = await db_session.connection()
    assert await st.rewrite_summaries(conn, room.room_id, summaries) == 2
    db_session.expire_all()
    after = await _snapshots(db_session, room.room_id)
    assert [s.summary_text for s in after] == ["B 요약 1", "B 요약 2"]
    assert [(s.id, s.cursor_message_id, s.source, s.previous_text) for s in after] == [
        (first.id, first.cursor_message_id, "auto", None),
        (second.id, second.cursor_message_id, "auto", None),
    ]
    assert [s.summary_text for s in await _snapshots(db_session, other.room_id)] == ["다른 방 요약"]


async def test_rewrite_refuses_when_any_room_snapshot_has_no_b_summary_and_changes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=4)
    await _plant_snapshot(db_session, room, turn=1, text="A 요약 1")
    await _plant_snapshot(db_session, room, turn=3, text="A 요약 2")
    first, _ = await _snapshots(db_session, room.room_id)
    conn = await db_session.connection()
    with pytest.raises(SystemExit, match="B 판 요약"):
        await st.rewrite_summaries(conn, room.room_id, {str(first.id): "B 요약 1"})
    db_session.expire_all()
    assert [s.summary_text for s in await _snapshots(db_session, room.room_id)] == ["A 요약 1", "A 요약 2"]


def test_summaries_file_refuses_duplicate_or_empty_rows(tmp_path: Path) -> None:
    path = tmp_path / "b.jsonl"
    path.write_text('{"snapshotId": "s1", "summary": "B"}\n\n{"snapshotId": "s2", "summary": "C"}\n', encoding="utf-8")
    assert st.load_summaries(path) == {"s1": "B", "s2": "C"}
    path.write_text('{"snapshotId": "s1", "summary": "B"}\n{"snapshotId": "s1", "summary": "C"}\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="두 번"):
        st.load_summaries(path)
    path.write_text('{"snapshotId": "s1", "summary": "  "}\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="비었다"):
        st.load_summaries(path)


def _fake_db(monkeypatch: pytest.MonkeyPatch, fingerprint: dict[str, Any]) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"clone": [], "rewrite": [], "drop": []}

    async def clone(url: str, *, source: str, target: str, replace: bool) -> None:
        calls["clone"].append((source, target, replace))

    async def rewrite(url: str, room_id: uuid.UUID, summaries: dict[str, str]) -> tuple[int, dict[str, Any], str]:
        calls["rewrite"].append(url.rsplit("/", 1)[1])
        return 3, dict(fingerprint), _b_digest()

    async def drop(url: str, name: str) -> None:
        calls["drop"].append(name)

    monkeypatch.setattr(checkpoint_mod, "clone_database", clone)
    monkeypatch.setattr(checkpoint_mod, "drop_database", drop)
    monkeypatch.setattr(st, "_rewrite_in", rewrite)
    return calls


URL = "postgresql+asyncpg://x@localhost/lm_eval_work"


def _a_digest() -> str:
    return checkpoint_mod.summary_digest(["A 요약 1", "A 요약 2"])


def _b_digest() -> str:
    return checkpoint_mod.summary_digest(["B 요약 1", "B 요약 2"])


async def test_derive_clones_each_checkpoint_into_the_b_label_and_copies_the_a_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fp = {"turnCount": 100, "snapshotCount": 3}
    calls = _fake_db(monkeypatch, fp)
    for cp in (100, 300):
        checkpoint_mod.write_fingerprint(checkpoint_mod.fingerprint_path(tmp_path, cp, "b1fc"), fp)
    (tmp_path / "b1fc-cp100.pinned.json").write_text('{"s": 1}', encoding="utf-8")
    result = await st.derive_b_templates(
        URL, room_id=uuid.uuid4(), base_label="b1fc", checkpoints=[100, 300], summaries={}, dumps_dir=tmp_path
    )
    b_label = series_label("b1fc", "b1-B1")
    assert calls["clone"] == [
        ("lm_eval_b1fc_cp100_frozen", f"lm_eval_{b_label}_cp100_frozen", True),
        ("lm_eval_b1fc_cp300_frozen", f"lm_eval_{b_label}_cp300_frozen", True),
    ]
    assert calls["rewrite"] == [f"lm_eval_{b_label}_cp100_frozen", f"lm_eval_{b_label}_cp300_frozen"]
    assert [r["summariesReplaced"] for r in result] == [3, 3]
    for cp in (100, 300):
        written = json.loads(checkpoint_mod.fingerprint_path(tmp_path, cp, b_label).read_text(encoding="utf-8"))
        assert written == {**fp, checkpoint_mod.SUMMARY_DIGEST_KEY: _b_digest()}
    assert (tmp_path / f"{b_label}-cp100.pinned.json").read_text(encoding="utf-8") == '{"s": 1}'
    assert not (tmp_path / f"{b_label}-cp300.pinned.json").exists()


async def test_derive_drops_the_b_template_when_the_fingerprint_moved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_db(monkeypatch, {"turnCount": 100, "snapshotCount": 4})
    checkpoint_mod.write_fingerprint(
        checkpoint_mod.fingerprint_path(tmp_path, 100, "b1fc"), {"turnCount": 100, "snapshotCount": 3}
    )
    b_label = series_label("b1fc", "b1-B1")
    with pytest.raises(SystemExit, match="지문"):
        await st.derive_b_templates(
            URL, room_id=uuid.uuid4(), base_label="b1fc", checkpoints=[100], summaries={}, dumps_dir=tmp_path
        )
    assert calls["drop"] == [f"lm_eval_{b_label}_cp100_frozen"]
    assert not checkpoint_mod.fingerprint_path(tmp_path, 100, b_label).exists()


async def test_derive_without_the_a_fingerprint_is_refused_before_cloning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_db(monkeypatch, {})
    with pytest.raises(SystemExit, match="지문"):
        await st.derive_b_templates(
            URL, room_id=uuid.uuid4(), base_label="b1fc", checkpoints=[100], summaries={}, dumps_dir=tmp_path
        )
    assert calls["clone"] == []


async def test_rerun_whose_rewrite_is_refused_drops_the_cloned_template_and_every_old_b_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_db(monkeypatch, {})

    async def refuse(url: str, room_id: uuid.UUID, summaries: dict[str, str]) -> tuple[int, dict[str, Any], str]:
        raise SystemExit("B 판 요약이 없는 스냅샷 1개")

    monkeypatch.setattr(st, "_rewrite_in", refuse)
    checkpoint_mod.write_fingerprint(checkpoint_mod.fingerprint_path(tmp_path, 100, "b1fc"), {"turnCount": 100})
    b_label = series_label("b1fc", "b1-B1")
    old_outputs = [
        checkpoint_mod.fingerprint_path(tmp_path, 100, b_label),
        checkpoint_mod.pinned_path(tmp_path, 100, b_label),
        checkpoint_mod.dump_path(tmp_path, 100, b_label),
    ]
    for path in old_outputs:
        path.write_text("지난 실행의 B 산출물", encoding="utf-8")
    with pytest.raises(SystemExit, match="템플릿을 지웠다") as refused:
        await st.derive_b_templates(
            URL, room_id=uuid.uuid4(), base_label="b1fc", checkpoints=[100], summaries={}, dumps_dir=tmp_path
        )
    assert "B 판 요약이 없는 스냅샷" in str(refused.value.code)
    assert calls["drop"] == [f"lm_eval_{b_label}_cp100_frozen"]
    assert [p.name for p in old_outputs if p.exists()] == []


async def test_summary_digest_follows_the_room_snapshot_text_so_a_and_b_templates_differ(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=4)
    await _plant_snapshot(db_session, room, turn=1, text="A 요약 1")
    await _plant_snapshot(db_session, room, turn=3, text="A 요약 2")
    first, second = await _snapshots(db_session, room.room_id)
    conn = await db_session.connection()
    assert await checkpoint_mod.compute_summary_digest(conn, room.room_id) == _a_digest()
    await st.rewrite_summaries(conn, room.room_id, {str(first.id): "B 요약 1", str(second.id): "B 요약 2"})
    assert await checkpoint_mod.compute_summary_digest(conn, room.room_id) == _b_digest()
    assert _a_digest() != _b_digest()


def _fake_restore(monkeypatch: pytest.MonkeyPatch, fingerprint: dict[str, Any], db_digest: str) -> list[str]:
    digest_reads: list[str] = []

    async def clone(url: str, *, source: str, target: str, replace: bool, lock: Path | None = None) -> None:
        return None

    async def clear(room_id: uuid.UUID, redis_url: str | None = None) -> list[str]:
        return []

    async def read_fp(url: str, room_id: uuid.UUID) -> dict[str, Any]:
        return dict(fingerprint)

    async def read_digest(url: str, room_id: uuid.UUID) -> str:
        digest_reads.append(url)
        return db_digest

    monkeypatch.setattr(checkpoint_mod, "clone_database", clone)
    monkeypatch.setattr(checkpoint_mod, "clear_room_redis_keys", clear)
    monkeypatch.setattr(checkpoint_mod, "read_fingerprint", read_fp)
    monkeypatch.setattr(checkpoint_mod, "read_summary_digest", read_digest)
    return digest_reads


async def _restore(tmp_path: Path, label: str, *, b_series: bool) -> dict[str, Any]:
    return await checkpoint_mod.restore(
        URL,
        work_db="lm_eval_work",
        checkpoint=100,
        room_id=uuid.uuid4(),
        dumps_dir=tmp_path,
        label=label,
        b_series=b_series,
    )


async def test_restore_refuses_a_b_template_whose_summaries_are_still_the_a_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fp = {"turnCount": 100, "snapshotCount": 2}
    b_label = series_label("b1fc", "b1-B1")
    checkpoint_mod.write_fingerprint(
        checkpoint_mod.fingerprint_path(tmp_path, 100, b_label), {**fp, checkpoint_mod.SUMMARY_DIGEST_KEY: _b_digest()}
    )
    _fake_restore(monkeypatch, fp, _a_digest())
    with pytest.raises(SystemExit, match=checkpoint_mod.SUMMARY_DIGEST_KEY):
        await _restore(tmp_path, b_label, b_series=True)

    _fake_restore(monkeypatch, fp, _b_digest())
    restored = await _restore(tmp_path, b_label, b_series=True)
    assert restored["fingerprint"][checkpoint_mod.SUMMARY_DIGEST_KEY] == _b_digest()


async def test_restore_of_an_a_template_does_not_read_the_summary_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fp = {"turnCount": 100, "snapshotCount": 2}
    checkpoint_mod.write_fingerprint(checkpoint_mod.fingerprint_path(tmp_path, 100, "b1fc"), fp)
    digest_reads = _fake_restore(monkeypatch, fp, _a_digest())
    assert (await _restore(tmp_path, "b1fc", b_series=False))["fingerprint"] == fp
    assert digest_reads == []


async def test_restore_of_an_a_template_whose_label_ends_like_the_b_suffix_needs_no_summary_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 대본 변형 이름이 B 계열 꼬리와 같은 글자로 끝나도, 계열은 이름이 아니라 호출자가 아는 갈래로 정한다.
    fp = {"turnCount": 100, "snapshotCount": 2}
    label = "b1fc-variant-b"
    assert label.endswith(B_SERIES_SUFFIX)
    checkpoint_mod.write_fingerprint(checkpoint_mod.fingerprint_path(tmp_path, 100, label), fp)
    digest_reads = _fake_restore(monkeypatch, fp, _a_digest())
    assert (await _restore(tmp_path, label, b_series=False))["fingerprint"] == fp
    assert digest_reads == []


async def test_restore_of_a_b_template_whose_saved_fingerprint_lacks_the_summary_digest_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 해시를 싣기 전에 얼린 B 지문은 이름에 꼬리가 없어도 B 계열로 부르면 칸 차이로 거부된다.
    fp = {"turnCount": 100, "snapshotCount": 2}
    checkpoint_mod.write_fingerprint(checkpoint_mod.fingerprint_path(tmp_path, 100, "b1fc"), fp)
    _fake_restore(monkeypatch, fp, _b_digest())
    with pytest.raises(SystemExit, match=checkpoint_mod.SUMMARY_DIGEST_KEY):
        await _restore(tmp_path, "b1fc", b_series=True)
