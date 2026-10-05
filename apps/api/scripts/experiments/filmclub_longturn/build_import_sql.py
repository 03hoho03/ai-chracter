"""측정 방을 다른 DB(운영)의 지정 계정 소유 새 방으로 옮기는 이식 SQL 을 만든다.

원본은 측정 방이 든 격리 Postgres 다. 값 리터럴은 원본 DB 의 `format('%L')` 로 만들어 이스케이프를 DB 에
맡기고, 손으로 문자열을 조립하지 않는다. 고정 버전 id 와 대상 계정 id 는 본문에 박지 않고 psql 변수로 받는다
(`psql -v version_id=… -v user_id=…`) — 그래야 같은 본문 파일을 격리 시험과 운영에 그대로 돌릴 수 있다.

출력 두 판은 끝줄만 다르다: `import-rehearsal.sql`(ROLLBACK) · `import-commit.sql`(COMMIT).
본문 구조: 변수 확인 → BEGIN·세션 고정(시간대·날짜 형식·잠금/문장 시간 제한) → 전제 검사 → INSERT 6 테이블 →
사후 불변식 → 끝줄. 사후 내용 대조용 md5 기대값은 원본에서 같은 시간대·날짜 형식으로 계산해 박는다.

생성 전에 원본의 측정 방 행이 보존 CSV 와 바이트 단위로 같은지(보존 COPY 질의 출력 sha256 = manifest)
먼저 확인한다 — 다르면 만들지 않는다.

사용:
  python build_import_sql.py --run-dir <RUN> --container <격리 postgres 컨테이너> [--db ai_character_chat]
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SESSION = "SET TimeZone = 'UTC'; SET DateStyle = 'ISO, YMD';"

# 대상 쪽에서 바뀌는 열(계정·고정 버전·배너 플래그·프로필)은 내용 대조에서 뺀다.
ROOM_MD5_COLS = (
    "id, content_id, starting_setup_entity_id, name, turn_count, ending_reached, ending_entity_id, "
    "ending_reached_at_turn, created_at, updated_at, memory_note, memory_version, memory_rolled_back_at"
)
MESSAGE_COLS = "id, chat_room_id, role, content, created_at, image_id"
SNAPSHOT_COLS = (
    "id, chat_room_id, cursor_created_at, cursor_message_id, summary_text, previous_text, source, "
    "created_at, updated_at, previous_source"
)
STAT_COLS = "chat_room_id, stat_entity_id, current_value"


def md5_query(table: str, cols: str, where: str, order: str) -> str:
    return (
        f"SELECT md5(coalesce(string_agg(row({cols})::text, E'\\n' ORDER BY {order}), '')) FROM {table} WHERE {where}"
    )


class Source:
    def __init__(self, container: str, db: str) -> None:
        self.container = container
        self.db = db

    def run(self, sql: str) -> str:
        proc = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                self.container,
                "psql",
                "-U",
                "postgres",
                "-d",
                self.db,
                "-X",
                "-At",
                "-q",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            input=f"{SESSION}\nBEGIN READ ONLY;\n{sql};\nROLLBACK;\n",
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            sys.exit(f"원본 질의 실패: {proc.stderr.strip()}")
        # -q 로 명령 태그(SET·BEGIN·ROLLBACK)를 끄므로 출력은 질의 값 하나뿐이다.
        return proc.stdout.removesuffix("\n")

    def copy(self, copy_sql: str) -> bytes:
        proc = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                self.container,
                "psql",
                "-U",
                "postgres",
                "-d",
                self.db,
                "-X",
                "-q",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            input=copy_sql.encode(),
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            sys.exit(f"보존 COPY 재실행 실패: {proc.stderr.decode().strip()}")
        return proc.stdout


def verify_source(src: Source, run_dir: Path, manifest: dict[str, Any]) -> None:
    for table, spec in manifest["tables"].items():
        out = src.copy((run_dir / "preserve" / spec["query"]).read_text())
        digest = hashlib.sha256(out).hexdigest()
        if digest != spec["sha256"]:
            sys.exit(f"원본 {table} 행이 보존 CSV 와 다르다: {digest} != {spec['sha256']}")


def build(src: Source, manifest: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    room = manifest["roomId"]
    content = manifest["contentId"]
    q_room = f"'{room}'"

    room_row = src.run(
        "SELECT format('(%L, :''user_id'', %L, :''version_id'', %L, %L, %L, %L, %L, %L, false, %L, %L, NULL, %L, %L, %L)', "
        "id, content_id, starting_setup_entity_id, name, turn_count, ending_reached, ending_entity_id, "
        "ending_reached_at_turn, created_at, updated_at, memory_note, memory_version, memory_rolled_back_at) "
        f"FROM chat_rooms WHERE id = {q_room}"
    )
    messages = src.run(
        f"SELECT string_agg(format('(%L, %L, %L, %L, %L, %L)', {MESSAGE_COLS}), E',\\n' ORDER BY created_at, id) "
        f"FROM chat_messages WHERE chat_room_id = {q_room}"
    )
    snapshots = src.run(
        f"SELECT string_agg(format('(%L, %L, %L, %L, %L, %L, %L, %L, %L, %L)', {SNAPSHOT_COLS}), E',\\n' "
        f"ORDER BY cursor_created_at, cursor_message_id, id) FROM chat_room_memory_snapshots WHERE chat_room_id = {q_room}"
    )
    stats = src.run(
        f"SELECT string_agg(format('(%L, %L, %L)', {STAT_COLS}), E',\\n' ORDER BY stat_entity_id) "
        f"FROM chat_room_stats WHERE chat_room_id = {q_room}"
    )
    # 노출: 방에서 다시 계산(오프닝 id 태그 = 방 생성 시각, 메시지 image_id = 처음 실린 메시지 시각, 칸별 최솟값).
    exposures = src.run(
        "WITH room AS (SELECT id, content_id, created_at FROM chat_rooms WHERE id = " + q_room + "), "
        "opening AS (SELECT m.content FROM chat_messages m, room WHERE m.chat_room_id = room.id AND m.role = 'ASSISTANT' "
        "ORDER BY m.created_at, m.id LIMIT 1), "
        "cells AS (SELECT (regexp_matches(opening.content, '\\{\\{img::([0-9a-f-]{36})\\}\\}', 'g'))[1]::uuid AS cell, "
        "room.created_at AS at FROM opening, room "
        "UNION ALL SELECT m.image_id, m.created_at FROM chat_messages m, room WHERE m.chat_room_id = room.id "
        "AND m.image_id IS NOT NULL) "
        "SELECT string_agg(format('(:''user_id'', %L, %L, %L)', content_id, cell, at), E',\\n' ORDER BY cell) "
        "FROM (SELECT room.content_id, cells.cell, min(cells.at) AS at FROM cells, room "
        "GROUP BY room.content_id, cells.cell) x"
    )
    unlocks = src.run(
        "SELECT coalesce(string_agg(format('(:''user_id'', %L, %L, %L)', u.starting_setup_entity_id, "
        "u.ending_entity_id, u.first_reached_at), E',\\n'), '') FROM story_ending_unlocks u JOIN chat_rooms r "
        f"ON r.id = {q_room} AND r.ending_reached AND u.user_id = r.user_id "
        "AND u.starting_setup_entity_id = r.starting_setup_entity_id AND u.ending_entity_id = r.ending_entity_id"
    )

    rid = f"'{room}'::uuid"
    md5_room = md5_query("chat_rooms", ROOM_MD5_COLS, f"id = {rid}", "id")
    md5_msg = md5_query("chat_messages", MESSAGE_COLS, f"chat_room_id = {rid}", "created_at, id")
    md5_snap = md5_query("chat_room_memory_snapshots", SNAPSHOT_COLS, f"chat_room_id = {rid}", "id")
    md5_stat = md5_query("chat_room_stats", STAT_COLS, f"chat_room_id = {rid}", "stat_entity_id")
    expected = {
        name: src.run(q).strip()
        for name, q in (("room", md5_room), ("messages", md5_msg), ("snapshots", md5_snap), ("stats", md5_stat))
    }

    meta = json.loads(
        src.run(
            "SELECT json_build_object('setup', starting_setup_entity_id, 'ending', ending_entity_id, "
            "'reached', ending_reached, 'turns', turn_count) FROM chat_rooms WHERE id = " + q_room
        )
    )
    stat_ids = src.run(
        f"SELECT string_agg(quote_literal(stat_entity_id), ',' ORDER BY stat_entity_id) "
        f"FROM chat_room_stats WHERE chat_room_id = {q_room}"
    ).strip()
    cell_ids = re.findall(r"\(:'user_id', '[^']+', '([0-9a-f-]{36})'", exposures)
    msg_ids = re.findall(r"^\('([0-9a-f-]{36})'", messages, flags=re.M)
    snap_ids = re.findall(r"^\('([0-9a-f-]{36})'", snapshots, flags=re.M)
    counts = {
        "chat_rooms": 1,
        "chat_messages": len(msg_ids),
        "chat_room_memory_snapshots": len(snap_ids),
        "chat_room_stats": stats.count("\n") + 1,
        "story_media_exposures": len(cell_ids),
        "story_ending_unlocks": unlocks.count("\n") + 1 if unlocks.strip() else 0,
    }
    for table, spec in manifest["tables"].items():
        if counts[table] != spec["rows"]:
            sys.exit(f"{table} 행 수 {counts[table]} != manifest {spec['rows']}")

    setup_e = f"'{meta['setup']}'::uuid"
    ending_e = f"'{meta['ending']}'::uuid" if meta["ending"] else "NULL::uuid"
    cells_arr = uuid_array(cell_ids)
    stats_arr = f"ARRAY[{stat_ids}]::uuid[]"

    body = f"""-- 측정 방 이식(생성물 — build_import_sql.py). 손으로 고치지 않는다.
-- 호출: psql -X -v version_id=<고정 버전 id> -v user_id=<대상 계정 id> < 이 파일
-- 방 {room} · 작품 {content} · 행 수 {json.dumps(counts, ensure_ascii=False)}
\\set ON_ERROR_STOP on
\\pset pager off
\\if :{{?version_id}}
\\else
\\echo 'version_id 변수가 없다'
SELECT 'version_id 변수가 없다'::int;
\\endif
\\if :{{?user_id}}
\\else
\\echo 'user_id 변수가 없다'
SELECT 'user_id 변수가 없다'::int;
\\endif
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';
SET LOCAL TimeZone = 'UTC';
SET LOCAL DateStyle = 'ISO, YMD';
SELECT set_config('s7.version_id', :'version_id', true), set_config('s7.user_id', :'user_id', true);
SELECT 'vars', current_setting('s7.version_id'), current_setting('s7.user_id'), current_setting('TimeZone'), current_setting('DateStyle');

-- 전제 검사: 하나라도 어긋나면 예외로 트랜잭션 전체가 취소된다.
DO $pre$
DECLARE
  v uuid := current_setting('s7.version_id')::uuid;
  u uuid := current_setting('s7.user_id')::uuid;
  setup_id uuid;
  n int;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM users WHERE id = u AND deleted_at IS NULL AND suspended_at IS NULL) THEN
    RAISE EXCEPTION '전제: 대상 계정이 없거나 탈퇴·정지 상태';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM content_versions WHERE id = v AND content_id = '{content}'::uuid AND published_at IS NOT NULL) THEN
    RAISE EXCEPTION '전제: 고정 버전이 없거나 작품 소속·발행이 아니다';
  END IF;
  SELECT count(*), max(id::text)::uuid INTO n, setup_id FROM starting_setups WHERE content_version_id = v AND entity_id = {setup_e};
  IF n <> 1 THEN RAISE EXCEPTION '전제: 시작설정 해석 % 행', n; END IF;
  IF (SELECT array_agg(entity_id ORDER BY entity_id) FROM stat_defs WHERE starting_setup_id = setup_id)
     IS DISTINCT FROM (SELECT array_agg(x ORDER BY x) FROM unnest({stats_arr}) x) THEN
    RAISE EXCEPTION '전제: 스탯 entity 집합이 고정 버전과 다르다';
  END IF;
  IF {"true" if meta["reached"] else "false"} AND NOT EXISTS (SELECT 1 FROM endings WHERE starting_setup_id = setup_id AND entity_id = {ending_e}) THEN
    RAISE EXCEPTION '전제: 엔딩이 고정 버전에서 해석되지 않는다';
  END IF;
  SELECT count(*) INTO n FROM unnest({cells_arr}) x
    WHERE NOT EXISTS (SELECT 1 FROM media_book_cells c WHERE c.content_version_id = v AND c.entity_id = x AND c.image_asset_id IS NOT NULL);
  IF n <> 0 THEN RAISE EXCEPTION '전제: 고정 버전에 없는 칸 %개', n; END IF;
  IF EXISTS (SELECT 1 FROM chat_rooms WHERE id = '{room}'::uuid) THEN RAISE EXCEPTION '전제: 방 id 충돌'; END IF;
  SELECT count(*) INTO n FROM chat_messages WHERE id = ANY({uuid_array(msg_ids)});
  IF n <> 0 THEN RAISE EXCEPTION '전제: 메시지 id 충돌 %개', n; END IF;
  SELECT count(*) INTO n FROM chat_room_memory_snapshots WHERE id = ANY({uuid_array(snap_ids)});
  IF n <> 0 THEN RAISE EXCEPTION '전제: 스냅샷 id 충돌 %개', n; END IF;
END
$pre$;
SELECT 'precheck', 'ok';

WITH ins AS (
INSERT INTO chat_rooms (id, user_id, content_id, content_version_id, starting_setup_entity_id, name, turn_count,
  ending_reached, ending_entity_id, ending_reached_at_turn, version_auto_upgraded, created_at, updated_at, persona_id,
  memory_note, memory_version, memory_rolled_back_at)
VALUES
{room_row}
RETURNING id)
SELECT 'inserted', 'chat_rooms', count(*), string_agg(id::text, ',') FROM ins;

WITH ins AS (
INSERT INTO chat_messages ({MESSAGE_COLS})
VALUES
{messages}
RETURNING id)
SELECT 'inserted', 'chat_messages', count(*) FROM ins;

WITH ins AS (
INSERT INTO chat_room_memory_snapshots ({SNAPSHOT_COLS})
VALUES
{snapshots}
RETURNING id)
SELECT 'inserted', 'chat_room_memory_snapshots', count(*) FROM ins;

WITH ins AS (
INSERT INTO chat_room_stats ({STAT_COLS})
VALUES
{stats}
RETURNING stat_entity_id)
SELECT 'inserted', 'chat_room_stats', count(*) FROM ins;

-- 사용자 단위 누적 기록: 이미 있던 키는 건드리지 않고, 실제로 들어간 키만 출력한다(되돌리기 목록).
WITH ins AS (
INSERT INTO story_media_exposures (user_id, content_id, cell_entity_id, first_exposed_at)
VALUES
{exposures}
ON CONFLICT DO NOTHING
RETURNING user_id, content_id, cell_entity_id, first_exposed_at)
SELECT 'rollback_key', 'story_media_exposures', user_id, content_id, cell_entity_id, first_exposed_at FROM ins ORDER BY cell_entity_id;
"""
    if unlocks.strip():
        body += f"""
WITH ins AS (
INSERT INTO story_ending_unlocks (user_id, starting_setup_entity_id, ending_entity_id, first_reached_at)
VALUES
{unlocks}
ON CONFLICT DO NOTHING
RETURNING user_id, starting_setup_entity_id, ending_entity_id, first_reached_at)
SELECT 'rollback_key', 'story_ending_unlocks', user_id, starting_setup_entity_id, ending_entity_id, first_reached_at FROM ins;
"""
    body += f"""
-- 사후 불변식: 행 수·내용 md5(원본과 같은 시간대·날짜 형식에서 계산한 값)·버전 해석·커서·첫 메시지.
DO $post$
DECLARE
  v uuid := current_setting('s7.version_id')::uuid;
  u uuid := current_setting('s7.user_id')::uuid;
  r uuid := '{room}'::uuid;
  setup_id uuid;
  n int;
BEGIN
  IF (SELECT count(*) FROM chat_rooms WHERE id = r AND user_id = u AND content_version_id = v AND persona_id IS NULL
      AND NOT version_auto_upgraded) <> 1 THEN RAISE EXCEPTION '사후: 방 행(치환 칸)'; END IF;
  IF (SELECT count(*) FROM chat_messages WHERE chat_room_id = r) <> {counts["chat_messages"]} THEN RAISE EXCEPTION '사후: 메시지 수'; END IF;
  IF (SELECT count(*) FROM chat_room_memory_snapshots WHERE chat_room_id = r) <> {counts["chat_room_memory_snapshots"]} THEN RAISE EXCEPTION '사후: 스냅샷 수'; END IF;
  IF (SELECT count(*) FROM chat_room_stats WHERE chat_room_id = r) <> {counts["chat_room_stats"]} THEN RAISE EXCEPTION '사후: 스탯 수'; END IF;
  IF ({md5_room.replace("'" + room + "'::uuid", "r")}) <> '{expected["room"]}' THEN RAISE EXCEPTION '사후: 방 내용 md5'; END IF;
  IF ({md5_msg.replace("'" + room + "'::uuid", "r")}) <> '{expected["messages"]}' THEN RAISE EXCEPTION '사후: 메시지 내용 md5'; END IF;
  IF ({md5_snap.replace("'" + room + "'::uuid", "r")}) <> '{expected["snapshots"]}' THEN RAISE EXCEPTION '사후: 스냅샷 내용 md5'; END IF;
  IF ({md5_stat.replace("'" + room + "'::uuid", "r")}) <> '{expected["stats"]}' THEN RAISE EXCEPTION '사후: 스탯 내용 md5'; END IF;
  SELECT count(*) INTO n FROM story_media_exposures WHERE user_id = u AND content_id = '{content}'::uuid AND cell_entity_id = ANY({cells_arr});
  IF n <> {counts["story_media_exposures"]} THEN RAISE EXCEPTION '사후: 노출 키 %/{counts["story_media_exposures"]}', n; END IF;
  IF {"true" if meta["reached"] else "false"} AND NOT EXISTS (SELECT 1 FROM story_ending_unlocks WHERE user_id = u
      AND starting_setup_entity_id = {setup_e} AND ending_entity_id = {ending_e}) THEN RAISE EXCEPTION '사후: 해금 키'; END IF;
  SELECT id INTO setup_id FROM starting_setups WHERE content_version_id = v AND entity_id = {setup_e};
  IF EXISTS (SELECT 1 FROM chat_room_stats s LEFT JOIN stat_defs d ON d.starting_setup_id = setup_id AND d.entity_id = s.stat_entity_id
      WHERE s.chat_room_id = r AND (d.id IS NULL OR s.current_value < d.min_value OR s.current_value > d.max_value)) THEN
    RAISE EXCEPTION '사후: 스탯 값이 정의 범위 밖이거나 정의가 없다';
  END IF;
  IF EXISTS (SELECT 1 FROM chat_messages m WHERE m.chat_room_id = r AND m.image_id IS NOT NULL AND NOT EXISTS
      (SELECT 1 FROM media_book_cells c WHERE c.content_version_id = v AND c.entity_id = m.image_id AND c.image_asset_id IS NOT NULL)) THEN
    RAISE EXCEPTION '사후: 고정 버전에 없는 칸을 가리키는 메시지';
  END IF;
  IF EXISTS (SELECT 1 FROM chat_room_memory_snapshots s WHERE s.chat_room_id = r AND NOT EXISTS
      (SELECT 1 FROM chat_messages m WHERE m.chat_room_id = r AND m.id = s.cursor_message_id AND m.created_at = s.cursor_created_at)) THEN
    RAISE EXCEPTION '사후: 요약 커서가 방 메시지를 가리키지 않는다';
  END IF;
  IF (SELECT role::text FROM chat_messages WHERE chat_room_id = r ORDER BY created_at, id LIMIT 1) <> 'ASSISTANT' THEN
    RAISE EXCEPTION '사후: 첫 메시지가 ASSISTANT 가 아니다';
  END IF;
  -- 첫 메시지의 id 태그 칸 ⊆ 고정 버전 오프닝 글이 가리키는 칸(이름 형태는 인물/장면 이름으로 해석).
  IF EXISTS (
    SELECT 1 FROM (SELECT content FROM chat_messages WHERE chat_room_id = r ORDER BY created_at, id LIMIT 1) f,
      LATERAL regexp_matches(f.content, '\\{{\\{{img::([0-9a-f-]{{36}})\\}}\\}}', 'g') AS t(g)
    WHERE t.g[1]::uuid NOT IN (
      SELECT c.entity_id FROM starting_setups s
        CROSS JOIN LATERAL regexp_matches(coalesce(s.opening_message, s.prologue), '\\{{\\{{img::([^{{}}]*)\\}}\\}}', 'g') AS m(g)
        JOIN media_book_cells c ON c.content_version_id = s.content_version_id
        LEFT JOIN media_book_people p ON p.content_version_id = c.content_version_id AND p.entity_id = c.person_entity_id
        LEFT JOIN media_book_scenes sc ON sc.content_version_id = c.content_version_id AND sc.entity_id = c.scene_entity_id
      WHERE s.id = setup_id AND (
        (m.g[1] ~ '^\\s*[0-9a-fA-F-]{{36}}\\s*$' AND c.entity_id = trim(m.g[1])::uuid) OR
        (m.g[1] ~ '^[^/]*/[^/]*$'
          AND normalize(trim(split_part(m.g[1], '/', 1)), NFC) = normalize(trim(p.name), NFC)
          AND normalize(trim(split_part(m.g[1], '/', 2)), NFC) = normalize(trim(sc.name), NFC))))
  ) THEN
    RAISE EXCEPTION '사후: 첫 메시지 칸이 고정 버전 오프닝 칸 밖이다';
  END IF;
END
$post$;
SELECT 'postcheck', 'ok';
-- 기록용(강제하지 않음): turn_count 와 사용자 메시지 수, 날짜별(UTC) 사용자 메시지 수(어드민 집계에 더해질 양).
SELECT 'record', 'turn_count', turn_count, (SELECT count(*) FROM chat_messages WHERE chat_room_id = '{room}'::uuid AND role = 'USER')
  FROM chat_rooms WHERE id = '{room}'::uuid;
SELECT 'record', 'user_messages_utc_date', created_at::date, count(*) FROM chat_messages
  WHERE chat_room_id = '{room}'::uuid AND role = 'USER' GROUP BY 1, 2, 3 ORDER BY 3;
"""
    info = {"counts": counts, "expectedMd5": expected, "statementKinds": statement_kinds(body)}
    return body, info


def uuid_array(ids: list[str]) -> str:
    return "ARRAY[" + ",".join(f"'{i}'" for i in ids) + "]::uuid[]"


def statement_kinds(body: str) -> dict[str, int]:
    """본문에 쓰기 문장이 INSERT 뿐인지 세어 둔다(줄 머리 기준 — 리터럴 안 글은 줄 머리에 키워드가 와도 세일 수 있어
    UPDATE·DELETE·TRUNCATE·DROP·ALTER 는 0 이어야 정상, 0 이 아니면 사람이 본다)."""
    kinds = ("INSERT INTO", "UPDATE ", "DELETE FROM", "TRUNCATE", "DROP ", "ALTER ")
    return {k.strip(): sum(1 for line in body.splitlines() if line.startswith(k)) for k in kinds}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--container", required=True)
    parser.add_argument("--db", default="ai_character_chat")
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "preserve" / "manifest.json").read_text())
    src = Source(args.container, args.db)
    verify_source(src, args.run_dir, manifest)
    body, info = build(src, manifest)

    out_dir = args.run_dir / "s7" / "sql"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "import-body.sql").write_text(body)
    (out_dir / "import-rehearsal.sql").write_text(body + "ROLLBACK;\n")
    (out_dir / "import-commit.sql").write_text(body + "COMMIT;\n")
    sha = {
        name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
        for name in ("import-body.sql", "import-rehearsal.sql", "import-commit.sql")
    }
    (out_dir / "build-info.json").write_text(
        json.dumps(
            {**info, "sha256": sha, "sourceDb": args.db, "sourceVerified": "보존 COPY 6개 sha256 = manifest"},
            ensure_ascii=False,
            indent=1,
        )
    )
    print(json.dumps({**info, "sha256": sha}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
