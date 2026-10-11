"""체크포인트 얼리기·복원과 상태 지문.

체크포인트마다 작업 DB 를 템플릿 DB(`lm_eval_cp<T>_frozen`)로 얼리고 `pg_dump -Fc` 백업도 남긴다. 프로브마다 서버를 내린 채
작업 DB 를 지우고 그 템플릿에서 다시 만든다(`DROP DATABASE` → `CREATE DATABASE … TEMPLATE`). 템플릿 복제는 원본에 다른 연결이
없어야 하므로 서버가 내려가 있어야 하고, 연결이 남아 있으면 끊지 않고 거부한다(누가 쥐고 있는지 모르는 연결을 끊지 않는다).

🔴 지우거나 템플릿으로 쓰는 DB 는 이름이 `lm_eval_` 로 시작하는 것만이다 — 격리 개발 DB·테스트 DB(같은 Postgres 를 다른
작업이 함께 쓴다)를 실수로 지우지 않게 이름으로 막는다.

Redis 는 통째로 비우지 않는다(세션 저장소가 같은 Redis 라 비우면 쿠키가 죽고 이메일당 로그인 상한에 걸린다). 그 방의 턴 락과
접기 백오프, 그리고 활성 프롬프트 세트 캐시만 지운다.

지문 = 스탯 값 · 엔딩 도달 · 턴 수 · 현재 요약 커서 · 스냅샷 수 · 에피소드 수(테이블이 있으면) · 메시지 수 · `memory_version`.
복원 직후 지문이 얼릴 때의 지문과 다르면 프로브를 보내지 않는다."""

import asyncio
import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

EVAL_DB_PREFIX = "lm_eval_"


def template_db_name(checkpoint: int) -> str:
    return f"{EVAL_DB_PREFIX}cp{checkpoint}_frozen"


def ensure_eval_db_name(name: str) -> None:
    if not name.startswith(EVAL_DB_PREFIX) or len(name) == len(EVAL_DB_PREFIX):
        raise SystemExit(f"평가 하네스는 이름이 {EVAL_DB_PREFIX} 로 시작하는 DB 만 지우거나 복제한다: {name!r}")


def fingerprint_diff(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    diffs = []
    for key in sorted(set(expected) | set(actual)):
        if key not in expected:
            diffs.append(f"{key}: 체크포인트 없음 → 지금 {actual[key]!r}")
        elif key not in actual:
            diffs.append(f"{key}: 체크포인트 {expected[key]!r} → 지금 없음")
        elif expected[key] != actual[key]:
            diffs.append(f"{key}: 체크포인트 {expected[key]!r} → 지금 {actual[key]!r}")
    return diffs


def database_name(database_url: str) -> str:
    name = make_url(database_url).database
    if not name:
        raise SystemExit("DATABASE_URL 에 DB 이름이 없다")
    return name


def maintenance_url(database_url: str) -> str:
    return make_url(database_url).set(database="postgres").render_as_string(hide_password=False)


async def _other_connections(conn: AsyncConnection, name: str) -> int:
    value = await conn.scalar(
        text("SELECT count(*) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()"), {"name": name}
    )
    return int(value or 0)


async def _exists(conn: AsyncConnection, name: str) -> bool:
    return bool(await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}))


async def clone_database(database_url: str, *, source: str, target: str, replace: bool) -> None:
    """`target` 을 `source` 의 복제로 만든다. `replace` 면 있던 `target` 을 먼저 지운다. 원본에 다른 연결이 있으면 거부."""
    ensure_eval_db_name(target)
    engine = create_async_engine(maintenance_url(database_url), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            busy = await _other_connections(conn, source)
            if busy:
                raise SystemExit(f"{source} 에 다른 연결 {busy}개 — 서버·드라이버를 내린 뒤 다시(연결을 끊지 않는다)")
            if await _exists(conn, target):
                if not replace:
                    raise SystemExit(f"{target} 이 이미 있다(덮으려면 replace)")
                busy_target = await _other_connections(conn, target)
                if busy_target:
                    raise SystemExit(f"{target} 에 다른 연결 {busy_target}개 — 서버를 내린 뒤 다시")
                await conn.execute(text(f'DROP DATABASE "{target}"'))
            await conn.execute(text(f'CREATE DATABASE "{target}" TEMPLATE "{source}"'))
    finally:
        await engine.dispose()


async def drop_database(database_url: str, name: str) -> None:
    ensure_eval_db_name(name)
    engine = create_async_engine(maintenance_url(database_url), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            if await _exists(conn, name):
                busy = await _other_connections(conn, name)
                if busy:
                    raise SystemExit(f"{name} 에 다른 연결 {busy}개")
                await conn.execute(text(f'DROP DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def pg_dump(container: str, db_user: str, name: str, out: Path) -> None:
    """격리 컨테이너 안의 `pg_dump -Fc` 를 표준 출력으로 받아 파일로 쓴다(호스트에 같은 판 클라이언트가 없어도 된다)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as handle:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            container,
            "pg_dump",
            "-U",
            db_user,
            "-Fc",
            name,
            stdout=handle,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
    if proc.returncode != 0:
        raise SystemExit(f"pg_dump 실패({proc.returncode}): {err.decode(errors='replace')[:300]}")


async def compute_fingerprint(conn: AsyncConnection, room_id: uuid.UUID) -> dict[str, Any]:
    room = (
        await conn.execute(
            text(
                "SELECT turn_count, ending_reached, ending_entity_id, memory_version FROM chat_rooms WHERE id = :room"
            ),
            {"room": room_id},
        )
    ).one()
    stats = {
        str(row.stat_entity_id): str(row.current_value)
        for row in await conn.execute(
            text("SELECT stat_entity_id, current_value FROM chat_room_stats WHERE chat_room_id = :room ORDER BY 1"),
            {"room": room_id},
        )
    }
    cursor_row = (
        await conn.execute(
            text(
                "SELECT cursor_created_at, cursor_message_id FROM chat_room_memory_snapshots WHERE chat_room_id = :room "
                "ORDER BY cursor_created_at DESC, cursor_message_id DESC LIMIT 1"
            ),
            {"room": room_id},
        )
    ).first()
    snapshots = await conn.scalar(
        text("SELECT count(*) FROM chat_room_memory_snapshots WHERE chat_room_id = :room"), {"room": room_id}
    )
    messages = await conn.scalar(
        text("SELECT count(*) FROM chat_messages WHERE chat_room_id = :room"), {"room": room_id}
    )
    episodes: int | None = None
    if await conn.scalar(text("SELECT to_regclass('chat_memory_episodes') IS NOT NULL")):
        episodes = int(
            await conn.scalar(
                text("SELECT count(*) FROM chat_memory_episodes WHERE chat_room_id = :room"), {"room": room_id}
            )
            or 0
        )
    return {
        "turnCount": int(room.turn_count),
        "endingReached": bool(room.ending_reached),
        "endingEntityId": str(room.ending_entity_id) if room.ending_entity_id else None,
        "memoryVersion": int(room.memory_version),
        "stats": stats,
        "cursor": [cursor_row.cursor_created_at.isoformat(), str(cursor_row.cursor_message_id)] if cursor_row else None,
        "snapshotCount": int(snapshots or 0),
        "messageCount": int(messages or 0),
        "episodeCount": episodes,
    }


async def read_fingerprint(database_url: str, room_id: uuid.UUID) -> dict[str, Any]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            return await compute_fingerprint(conn, room_id)
    finally:
        await engine.dispose()


def fingerprint_path(dumps_dir: Path, checkpoint: int) -> Path:
    return dumps_dir / f"cp{checkpoint}.fingerprint.json"


def write_fingerprint(path: Path, fingerprint: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fingerprint, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


async def clear_room_redis_keys(room_id: uuid.UUID) -> list[str]:
    """그 방의 턴 락·접기 백오프와 활성 프롬프트 세트 캐시만 지운다. `FLUSHDB`·`FLUSHALL` 은 쓰지 않는다."""
    from api.chat.prompt_set_cache import ACTIVE_PROMPT_SET_KEY_PREFIX
    from api.core.redis import redis_client

    keys = [f"chat_room:turn_lock:{room_id}", f"memory_fold_backoff:{room_id}"]
    keys += [key async for key in redis_client.scan_iter(match=f"{ACTIVE_PROMPT_SET_KEY_PREFIX}*")]
    deleted = []
    for key in keys:
        if await redis_client.delete(key):
            deleted.append(key)
    return deleted


async def freeze(
    database_url: str,
    *,
    work_db: str,
    checkpoint: int,
    room_id: uuid.UUID,
    dumps_dir: Path,
    container: str | None,
    db_user: str,
) -> dict[str, Any]:
    """작업 DB 를 템플릿으로 얼리고 지문을 남긴다. 컨테이너를 주면 `pg_dump -Fc` 백업도."""
    ensure_eval_db_name(work_db)
    fingerprint = await read_fingerprint(database_url, room_id)
    template = template_db_name(checkpoint)
    await clone_database(database_url, source=work_db, target=template, replace=True)
    write_fingerprint(fingerprint_path(dumps_dir, checkpoint), fingerprint)
    if container:
        await pg_dump(container, db_user, template, dumps_dir / f"cp{checkpoint}.dump")
    return {"template": template, "fingerprint": fingerprint}


async def restore(
    database_url: str, *, work_db: str, checkpoint: int, room_id: uuid.UUID, dumps_dir: Path
) -> dict[str, Any]:
    """작업 DB 를 템플릿에서 다시 만들고 방 Redis 키를 지운 뒤 지문을 단언한다. 다르면 `SystemExit`."""
    ensure_eval_db_name(work_db)
    await clone_database(database_url, source=template_db_name(checkpoint), target=work_db, replace=True)
    deleted = await clear_room_redis_keys(room_id)
    expected = json.loads(fingerprint_path(dumps_dir, checkpoint).read_text(encoding="utf-8"))
    actual = await read_fingerprint(database_url, room_id)
    diffs = fingerprint_diff(expected, actual)
    if diffs:
        raise SystemExit("복원 뒤 지문이 체크포인트와 다르다: " + "; ".join(diffs))
    return {"redisDeleted": deleted, "fingerprint": actual}
