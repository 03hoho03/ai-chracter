"""두 템플릿 계열 — 요약 표기가 켜진 갈래(B 계열)의 체크포인트 템플릿을 A 계열 템플릿에서 만든다.

계열마다 따로 투입하면 장면·사실 추출이 LLM 무작위로 달라져, 요약 표기 갈래와 그 직전 갈래의 차이에 추출 잡음이 섞인다. 그래서
투입은 한 번 하고(접기마다 요약을 두 판으로 함께 만든다), B 계열 템플릿은 A 계열 템플릿을 복제한 뒤 그 방 스냅샷의 요약 글만
B 판으로 바꾼다. 스냅샷 행을 제자리에서 고치므로 장면·사실 행이 가리키는 스냅샷 FK 는 그대로다.

B 판 요약 파일은 줄마다 `{"snapshotId": "<스냅샷 id>", "summary": "<B 판 요약 글>"}` 이다. 템플릿 하나의 방 스냅샷 가운데
B 판이 없는 것이 하나라도 있으면 아무것도 바꾸지 않고 거부한다 — 일부만 바뀐 템플릿은 두 계열이 섞인 상태다. 파일에 그
템플릿에 없는 스냅샷이 더 있는 것은 괜찮다(뒤 체크포인트에서 생긴 스냅샷). 바꾼 뒤 지문(요약 글은 지문에 없다)이 A 계열
지문과 다르면 만든 템플릿을 지우고 거부한다.

다시 만들 때는 복제가 옛 B 템플릿을 A 복제본으로 덮으므로, 복제 전에 옛 B 지문·고정 스탯·덤프를 지우고 요약 바꾸기가
거부되면 복제한 템플릿도 지운다 — 그래야 A 요약이 든 B 템플릿이 옛 B 지문으로 복원을 통과하지 못한다. B 지문에는 바꾼 요약
글의 해시를 더 싣는다(복원이 B 계열 이름이면 그 해시를 DB 와 견준다)."""

import json
import shutil
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from memory_eval import checkpoint
from memory_eval.arm_env import B_SERIES_SUFFIX


def load_summaries(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        snapshot_id, summary = str(row["snapshotId"]), str(row.get("summary") or "")
        if snapshot_id in out:
            raise SystemExit(f"B 판 요약 파일에 스냅샷 {snapshot_id} 가 두 번 있다")
        if not summary.strip():
            raise SystemExit(f"B 판 요약 파일의 스냅샷 {snapshot_id} 요약이 비었다")
        out[snapshot_id] = summary
    return out


async def rewrite_summaries(conn: AsyncConnection, room_id: uuid.UUID, summaries: Mapping[str, str]) -> int:
    """그 방 스냅샷의 요약 글을 B 판으로 바꾸고 바꾼 행 수를 돌려준다. 다른 칸(커서·출처·되돌리기 값)은 건드리지 않는다."""
    ids = [
        str(row)
        for row in await conn.scalars(
            text(
                "SELECT id FROM chat_room_memory_snapshots WHERE chat_room_id = :room "
                "ORDER BY cursor_created_at, cursor_message_id"
            ),
            {"room": room_id},
        )
    ]
    missing = [i for i in ids if i not in summaries]
    if missing:
        raise SystemExit(f"B 판 요약이 없는 스냅샷 {len(missing)}개 — 요약 글을 하나도 바꾸지 않았다: {missing[:5]}")
    for snapshot_id in ids:
        await conn.execute(
            text("UPDATE chat_room_memory_snapshots SET summary_text = :summary WHERE id = :id"),
            {"summary": summaries[snapshot_id], "id": uuid.UUID(snapshot_id)},
        )
    return len(ids)


async def _rewrite_in(url: str, room_id: uuid.UUID, summaries: Mapping[str, str]) -> tuple[int, dict[str, Any], str]:
    """그 DB 에 붙어 요약 글을 바꾸고 지문과 요약 글 해시를 읽는다. 한 트랜잭션이라 거부되면 그 DB 의 요약은 복제한 A 판
    그대로다."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            replaced = await rewrite_summaries(conn, room_id, summaries)
            fingerprint = await checkpoint.compute_fingerprint(conn, room_id)
            digest = await checkpoint.compute_summary_digest(conn, room_id)
    finally:
        await engine.dispose()
    return replaced, fingerprint, digest


def _remove_b_outputs(dumps_dir: Path, cp: int, b_label: str) -> None:
    for path in (
        checkpoint.fingerprint_path(dumps_dir, cp, b_label),
        checkpoint.pinned_path(dumps_dir, cp, b_label),
        checkpoint.dump_path(dumps_dir, cp, b_label),
    ):
        path.unlink(missing_ok=True)


async def derive_b_templates(
    database_url: str,
    *,
    room_id: uuid.UUID,
    base_label: str,
    checkpoints: Sequence[int],
    summaries: Mapping[str, str],
    dumps_dir: Path,
    container: str | None = None,
    db_user: str = "postgres",
) -> list[dict[str, Any]]:
    """체크포인트마다 A 계열 템플릿(`base_label`)을 B 계열 이름으로 복제하고 요약 글을 바꾼 뒤, A 계열 지문과 같은지 보고 B 계열
    지문 파일(고정 스탯 파일이 있으면 그것도)을 남긴다. 컨테이너를 주면 `pg_dump -Fc` 백업도 남긴다."""
    b_label = base_label + B_SERIES_SUFFIX
    out: list[dict[str, Any]] = []
    for cp in checkpoints:
        a_fingerprint = checkpoint.fingerprint_path(dumps_dir, cp, base_label)
        if not a_fingerprint.exists():
            raise SystemExit(f"A 계열 cp{cp} 지문이 없다 — 그 템플릿을 얼린 넣기 실행을 먼저: {a_fingerprint}")
        expected = json.loads(a_fingerprint.read_text(encoding="utf-8"))
        target = checkpoint.template_db_name(cp, b_label)
        _remove_b_outputs(dumps_dir, cp, b_label)
        await checkpoint.clone_database(
            database_url, source=checkpoint.template_db_name(cp, base_label), target=target, replace=True
        )
        url = make_url(database_url).set(database=target).render_as_string(hide_password=False)
        try:
            replaced, actual, digest = await _rewrite_in(url, room_id, summaries)
        except (SystemExit, Exception) as refused:
            await checkpoint.drop_database(database_url, target)
            reason = refused.code if isinstance(refused, SystemExit) else repr(refused)
            raise SystemExit(
                f"B 계열 cp{cp} 요약을 B 판으로 바꾸지 못했다 — A 복제본이 된 B 템플릿을 지웠다(옛 B 지문·고정 스탯·덤프도 "
                f"지운 상태다): {reason}"
            ) from refused
        diffs = checkpoint.fingerprint_diff(expected, actual)
        if diffs:
            await checkpoint.drop_database(database_url, target)
            raise SystemExit(f"B 계열 cp{cp} 지문이 A 계열과 다르다(템플릿을 지웠다): " + "; ".join(diffs))
        checkpoint.write_fingerprint(
            checkpoint.fingerprint_path(dumps_dir, cp, b_label), {**actual, checkpoint.SUMMARY_DIGEST_KEY: digest}
        )
        pinned = checkpoint.pinned_path(dumps_dir, cp, base_label)
        if pinned.exists():
            shutil.copyfile(pinned, checkpoint.pinned_path(dumps_dir, cp, b_label))
        if container:
            await checkpoint.pg_dump(container, db_user, target, checkpoint.dump_path(dumps_dir, cp, b_label))
        out.append({"checkpoint": cp, "template": target, "summariesReplaced": replaced})
    return out
