"""체크포인트 얼리기·복원과 상태 지문.

체크포인트마다 작업 DB 를 템플릿 DB(`lm_eval_<단계>_cp<T>_frozen`)로 얼리고 `pg_dump -Fc` 백업도 남긴다. 프로브마다 서버를 내린 채
작업 DB 를 지우고 그 템플릿에서 다시 만든다(`DROP DATABASE` → `CREATE DATABASE … TEMPLATE`). 템플릿 복제는 원본에 다른 연결이
없어야 하므로 서버가 내려가 있어야 하고, 연결이 남아 있으면 끊지 않고 거부한다(누가 쥐고 있는지 모르는 연결을 끊지 않는다).

🔴 지우거나 템플릿으로 쓰는 DB 는 이름이 `lm_eval_` 로 시작하는 것만이다 — 격리 개발 DB·테스트 DB(같은 Postgres 를 다른
작업이 함께 쓴다)를 실수로 지우지 않게 이름으로 막는다.

Redis 는 통째로 비우지 않는다(세션 저장소가 같은 Redis 라 비우면 쿠키가 죽고 이메일당 로그인 상한에 걸린다). 그 방의 턴 락과
접기 백오프, 그리고 활성 프롬프트 세트 캐시만 지운다.

지문 = 스탯 값 · 엔딩 도달 · 턴 수 · 현재 요약 커서 · 스냅샷 수 · 에피소드 수(테이블이 있으면) · 사실 행 수(사실 테이블
`chat_memory_facts` 가 있을 때만 칸이 생긴다 — 그 테이블이 없던 때 얼린 지문과 견줘도 칸 차이가 나지 않게) · 임베딩 행 수와
어떤 임베딩도 없는 장면·사실 행 수(임베딩 표 `chat_memory_embeddings` 가 있을 때만, 같은 이유) · 메시지 수 · `memory_version`.
복원 직후 지문이 얼릴 때의 지문과 다르면 프로브를 보내지 않는다.

B 계열 템플릿(요약 글만 다른 판으로 바꾼 것)의 지문에는 그 방 스냅샷 요약 글의 해시가 더 실린다 — 위 칸들은 요약 글을 보지
않아, 요약이 A 판으로 남은 B 템플릿도 지문이 같다. B 계열 이름으로 복원하면 이 해시도 DB 와 견준다."""

import asyncio
import contextlib
import fcntl
import hashlib
import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

EVAL_DB_PREFIX = "lm_eval_"
SUMMARY_DIGEST_KEY = "summaryDigest"


def template_db_name(checkpoint: int, label: str) -> str:
    """단계(`label`)가 이름에 들어가 기준선과 최종 비교의 템플릿이 서로 덮지 않는다."""
    return f"{EVAL_DB_PREFIX}{label}_cp{checkpoint}_frozen"


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


@contextlib.contextmanager
def _file_lock(path: Path | None) -> Iterator[None]:
    """`path` 의 `fcntl.flock` 배타 잠금(없으면 잠그지 않는다). 잠금은 연 파일 단위라 같은 프로세스의 다른 스레드도 기다린다."""
    if path is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


async def clone_database(
    database_url: str, *, source: str, target: str, replace: bool, lock: Path | None = None
) -> None:
    """`target` 을 `source` 의 복제로 만든다. `replace` 면 있던 `target` 을 먼저 지운다. 원본에 다른 연결이 있으면 거부.

    `lock` 을 주면 연결 검사부터 복제까지를 그 파일 잠금 안에서 한다 — 프로브 작업자 여럿이 같은 템플릿을 저마다의 작업 DB 로
    복제할 때 한 번에 하나씩만 한다. 같은 템플릿의 동시 복제가 실패한다는 근거를 잰 적은 없다(복제 명령은 원본이 아니라 관리 DB
    연결에서 나간다). 연결 검사와 복제 사이에 다른 작업자의 복제·삭제가 끼지 않게 하는 안전판이고, 복제는 1초 안팎이라 줄 세워도
    비용이 작다. 턴을 보내는 동안은 잠그지 않는다."""
    ensure_eval_db_name(target)
    with _file_lock(lock):
        await _clone(database_url, source=source, target=target, replace=replace)


async def _clone(database_url: str, *, source: str, target: str, replace: bool) -> None:
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
    facts: dict[str, int] = {}
    if await conn.scalar(text("SELECT to_regclass('chat_memory_facts') IS NOT NULL")):
        facts["factCount"] = int(
            await conn.scalar(
                text("SELECT count(*) FROM chat_memory_facts WHERE chat_room_id = :room"), {"room": room_id}
            )
            or 0
        )
    if await conn.scalar(text("SELECT to_regclass('chat_memory_embeddings') IS NOT NULL")):
        facts["embeddingCount"] = int(
            await conn.scalar(
                text("SELECT count(*) FROM chat_memory_embeddings WHERE chat_room_id = :room"), {"room": room_id}
            )
            or 0
        )
        facts["unembeddedCount"] = int(
            await conn.scalar(
                text(
                    "SELECT (SELECT count(*) FROM chat_memory_episodes e WHERE e.chat_room_id = :room AND NOT EXISTS "
                    "(SELECT 1 FROM chat_memory_embeddings m WHERE m.episode_id = e.id)) + "
                    "(SELECT count(*) FROM chat_memory_facts f WHERE f.chat_room_id = :room AND NOT EXISTS "
                    "(SELECT 1 FROM chat_memory_embeddings m WHERE m.fact_id = f.id))"
                ),
                {"room": room_id},
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
        **facts,
    }


async def read_fingerprint(database_url: str, room_id: uuid.UUID) -> dict[str, Any]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            return await compute_fingerprint(conn, room_id)
    finally:
        await engine.dispose()


def summary_digest(texts: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(list(texts), ensure_ascii=False).encode("utf-8")).hexdigest()


async def compute_summary_digest(conn: AsyncConnection, room_id: uuid.UUID) -> str:
    """그 방 스냅샷 요약 글을 커서 순으로 모은 해시."""
    texts = await conn.scalars(
        text(
            "SELECT summary_text FROM chat_room_memory_snapshots WHERE chat_room_id = :room "
            "ORDER BY cursor_created_at, cursor_message_id"
        ),
        {"room": room_id},
    )
    return summary_digest([str(t) for t in texts])


async def read_summary_digest(database_url: str, room_id: uuid.UUID) -> str:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            return await compute_summary_digest(conn, room_id)
    finally:
        await engine.dispose()


def fingerprint_path(dumps_dir: Path, checkpoint: int, label: str) -> Path:
    return dumps_dir / f"{label}-cp{checkpoint}.fingerprint.json"


def write_fingerprint(path: Path, fingerprint: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fingerprint, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


async def clear_room_redis_keys(room_id: uuid.UUID, redis_url: str | None = None) -> list[str]:
    """그 방의 턴 락·접기 백오프, 활성 프롬프트 세트 캐시, 전역 Voyage 연속 실패 멈춤 키만 지운다. `FLUSHDB`·`FLUSHALL` 은 쓰지
    않는다.

    Voyage 멈춤 키는 방과 무관한 키 하나라 방 키만 지우면 앞 프로브(또는 어긋난 임베딩 클라이언트)가 남긴 연속 실패 수가 하루
    동안 다음 프로브로 넘어가고, 문턱을 넘으면 다음 프로브의 질의 임베딩이 통째로 건너뛰어져 임베딩 회상 갈래가 명사 단독으로
    재진다.

    앱의 모듈 싱글턴 Redis 클라이언트를 쓰지 않고 호출마다 연결을 만들어 이 루프 안에서 닫는다 — 프로브는 시도마다
    `asyncio.run` 으로 새 이벤트 루프를 열고, 싱글턴은 처음 쓴 루프에 묶여 두 번째 루프에서 "다른 루프에 붙은 Future" 로
    죽는다.

    `redis_url` 은 측정 서버가 쓰는 Redis 다(프로브 작업자마다 번호가 다르다). 주지 않으면 이 프로세스 설정의 Redis — 서버를 같은
    `.env` 로 띄울 때만 맞다. 서버 env 에만 작업자 Redis 를 주고 여기서 다른 번호를 지우면 서버 쪽 턴 락·멈춤 키가 그대로 남는다."""
    from redis.asyncio import Redis

    from api.chat.prompt_set_cache import ACTIVE_PROMPT_SET_KEY_PREFIX
    from api.chat.voyage_backoff import VOYAGE_BACKOFF_KEY
    from api.core.config import settings

    client = Redis.from_url(redis_url or settings.redis_url, decode_responses=True)
    try:
        keys = [f"chat_room:turn_lock:{room_id}", f"memory_fold_backoff:{room_id}", VOYAGE_BACKOFF_KEY]
        keys += [key async for key in client.scan_iter(match=f"{ACTIVE_PROMPT_SET_KEY_PREFIX}*")]
        deleted = []
        for key in keys:
            if await client.delete(key):
                deleted.append(key)
        return deleted
    finally:
        await client.aclose()


async def require_no_voyage_backoff(redis_url: str | None = None) -> None:
    """전역 Voyage 연속 실패 멈춤 키가 없음을 단언한다(프로브 턴을 보내기 직전). 있으면 그 프로브의 질의 임베딩이 건너뛰어질 수
    있으므로 `SystemExit` — 복원이 지웠는데도 남아 있다면 다른 프로세스가 같은 Redis 에서 Voyage 를 부르고 있다. `redis_url` 은
    `clear_room_redis_keys` 와 같은 뜻(측정 서버가 쓰는 Redis)."""
    from redis.asyncio import Redis

    from api.chat.voyage_backoff import VOYAGE_BACKOFF_KEY
    from api.core.config import settings

    client = Redis.from_url(redis_url or settings.redis_url, decode_responses=True)
    try:
        if await client.exists(VOYAGE_BACKOFF_KEY):
            raise SystemExit(
                f"Redis 에 Voyage 연속 실패 멈춤 키({VOYAGE_BACKOFF_KEY})가 있다 — 이대로 보내면 질의 임베딩이 건너뛰어져 임베딩 "
                "회상 갈래가 명사 단독으로 재진다. 같은 Redis 를 쓰는 다른 서버·작업을 확인한다"
            )
    finally:
        await client.aclose()


async def freeze(
    database_url: str,
    *,
    work_db: str,
    checkpoint: int,
    room_id: uuid.UUID,
    dumps_dir: Path,
    container: str | None,
    db_user: str,
    label: str,
    require_episode_rows: bool,
) -> dict[str, Any]:
    """작업 DB 를 템플릿으로 얼리고 지문을 남긴다. 컨테이너를 주면 `pg_dump -Fc` 백업도. 추출을 켠 실행이면 에피소드가
    있어야 얼린다."""
    ensure_eval_db_name(work_db)
    fingerprint = await read_fingerprint(database_url, room_id)
    require_episodes(fingerprint, required=require_episode_rows)
    template = template_db_name(checkpoint, label)
    await clone_database(database_url, source=work_db, target=template, replace=True)
    write_fingerprint(fingerprint_path(dumps_dir, checkpoint, label), fingerprint)
    if container:
        await pg_dump(container, db_user, template, dump_path(dumps_dir, checkpoint, label))
    return {"template": template, "fingerprint": fingerprint}


async def restore(
    database_url: str,
    *,
    work_db: str,
    checkpoint: int,
    room_id: uuid.UUID,
    dumps_dir: Path,
    label: str,
    b_series: bool,
    redis_url: str | None = None,
    clone_lock: Path | None = None,
) -> dict[str, Any]:
    """템플릿으로 작업 DB 를 새로 복제하고, 이 방의 Redis 키를 정리한 다음 지문이 같은지 확인한다. 다르면 `SystemExit`. B 계열
    템플릿이면(`b_series`) 요약 글 해시도 지문에 넣어 견준다 — 해시가 없는 B 지문(해시를 싣기 전에 만든 것)도 칸 차이로 거부된다.
    계열은 이름 꼬리로 짐작하지 않고 호출자가 아는 갈래로 받는다 — 대본 변형 이름이 우연히 B 꼬리로 끝나면 A 템플릿을 B 로 잘못
    읽는다. `redis_url`·`clone_lock` 은 프로브 작업자의 Redis 와 복제 잠금(`clear_room_redis_keys`·`clone_database`)."""
    ensure_eval_db_name(work_db)
    await clone_database(
        database_url, source=template_db_name(checkpoint, label), target=work_db, replace=True, lock=clone_lock
    )
    deleted = await clear_room_redis_keys(room_id, redis_url)
    expected = json.loads(fingerprint_path(dumps_dir, checkpoint, label).read_text(encoding="utf-8"))
    actual = await read_fingerprint(database_url, room_id)
    if b_series:
        actual[SUMMARY_DIGEST_KEY] = await read_summary_digest(database_url, room_id)
    diffs = fingerprint_diff(expected, actual)
    if diffs:
        raise SystemExit("복원 뒤 지문이 체크포인트와 다르다: " + "; ".join(diffs))
    pinned_file = pinned_path(dumps_dir, checkpoint, label)
    if pinned_file.exists():
        from memory_eval.pinned_stats import pinned_diff

        pinned = {k: float(v) for k, v in json.loads(pinned_file.read_text(encoding="utf-8")).items()}
        off = pinned_diff(actual["stats"], pinned)
        if off:
            raise SystemExit("복원 뒤 스탯이 고정 값과 다르다: " + "; ".join(off))
    return {"redisDeleted": deleted, "fingerprint": actual}


def require_episodes(fingerprint: Mapping[str, Any], *, required: bool) -> None:
    """추출을 켠 실행(또는 회상 갈래)의 체크포인트는 에피소드가 있어야 한다 — 0 이면 추출이 조용히 실패한 상태로 얼린다."""
    if required and not fingerprint.get("episodeCount"):
        raise SystemExit(
            f"에피소드가 없는 상태로 얼리려 한다(episodeCount={fingerprint.get('episodeCount')!r}) — 추출 확인"
        )


def pinned_path(dumps_dir: Path, checkpoint: int, label: str) -> Path:
    """얼릴 때 고정한 스탯(entity_id → 값). 있으면 복원 뒤 지문의 스탯이 이 값과 같은지도 단언한다."""
    return dumps_dir / f"{label}-cp{checkpoint}.pinned.json"


def dump_path(dumps_dir: Path, checkpoint: int, label: str) -> Path:
    return dumps_dir / f"{label}-cp{checkpoint}.dump"
