"""운영에서 내보낸 조감독 발행본과 프롬프트 세트 3개를 격리 DB 에 같은 UUID 로 넣는다.

입력은 split_export.py 가 만든 테이블별 JSON. 각 테이블의 열 목록은 격리 DB 의
information_schema 에서 읽어 JSON 키 집합과 정확히 같은지 먼저 확인하고(다르면 멈춤),
INSERT 문에 열 이름을 전부 적는다. 운영 값을 그대로 옮기되 아래만 바꾼다.

- 작품 작가·자산 소유자 → 격리 DB 의 작가 계정(users 행은 옮기지 않는다)
- 장르 → 격리 DB 에서 같은 이름의 장르
- 자산의 생성 요청 id → NULL(생성 요청 행을 옮기지 않는다)
- 조회수·좋아요·대화 수 → 0, 고정 댓글 → NULL(댓글을 옮기지 않는다)
- 작품의 현행 발행 버전은 처음엔 NULL 로 넣고 버전 행을 넣은 뒤 UPDATE 한다(서로 FK 로 가리킨다)
- 프롬프트 세트의 published_at → 지금. 활성 세트는 레인별 published_at 최신이고, 격리 DB 의
  마이그레이션 세트는 업그레이드 시각으로 찍혀 있어 운영 원값으로는 활성이 되지 않는다.

기본은 마지막에 ROLLBACK 하는 시험 실행이고 --commit 을 줘야 반영한다.
사용: python import_replica.py <JSON 디렉터리> <작가 이메일> [--commit]
"""

import json
import subprocess
import sys
from pathlib import Path

CONTAINER = "ai-character-chat-wt-filmclub-longturn-postgres-1"
PSQL = ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", "ai_character_chat", "-X", "-At"]

# FK 가 가리키는 쪽부터. contents 는 현행 버전 없이 먼저 들어간다.
ORDER = [
    "assets",
    "contents",
    "content_versions",
    "story_version_details",
    "starting_setups",
    "stat_defs",
    "endings",
    "ending_rule_groups",
    "ending_rules",
    "keyword_notes",
    "shortcuts",
    "situation_notes",
    "media_book_people",
    "media_book_scenes",
    "media_book_cells",
    "prompt_sets",
    "prompt_sections",
]

DOLLAR = "$replica$"


def psql(sql: str) -> str:
    return subprocess.run(PSQL, input=sql, capture_output=True, text=True, check=True).stdout


def columns(table: str) -> list[str]:
    out = psql(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema = 'public' AND table_name = '{table}' ORDER BY ordinal_position;"
    )
    return out.split()


def main() -> None:
    src, creator_email = Path(sys.argv[1]), sys.argv[2]
    commit = "--commit" in sys.argv[3:]
    genre_name = json.loads((src / "genre_name.json").read_text())[0]["name"]
    creator = f"(SELECT id FROM users WHERE email = '{creator_email}')"
    overrides = {
        "assets": {"owner_user_id": creator, "request_id": "NULL"},
        "contents": {
            "creator_user_id": creator,
            "genre_id": f"(SELECT id FROM genres WHERE name = '{genre_name}')",
            "current_published_version_id": "NULL",
            "pinned_comment_id": "NULL",
            "view_count": "0",
            "like_count": "0",
            "chat_count": "0",
        },
        "prompt_sets": {"published_at": "now()"},
    }

    stmts = ["\\set ON_ERROR_STOP on", "BEGIN;"]
    # 작가 계정·장르가 없으면 서브쿼리가 NULL 이 되어 NOT NULL 에서 터지지만, 이유가 보이게 먼저 확인한다.
    stmts.append(
        f"DO $$ BEGIN IF {creator} IS NULL THEN RAISE EXCEPTION '작가 계정 없음'; END IF; "
        f"IF (SELECT id FROM genres WHERE name = '{genre_name}') IS NULL THEN RAISE EXCEPTION '장르 없음'; END IF; END $$;"
    )
    sets = json.loads((src / "prompt_sets.json").read_text())
    for s in sets:
        # 게시본 (lane, version) 부분 유니크 충돌을 넣기 전에 이름 붙여 드러낸다.
        stmts.append(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM prompt_sets WHERE status = 'published' "
            f"AND lane = '{s['lane']}' AND version = '{s['version']}') THEN "
            f"RAISE EXCEPTION 'version 충돌: {s['lane']} {s['version']}'; END IF; END $$;"
        )
    for table in ORDER:
        rows = json.loads((src / f"{table}.json").read_text())
        if not rows:
            print(f"{table}\t0행(건너뜀)")
            continue
        cols = columns(table)
        keys = set(rows[0])
        if set(cols) != keys or any(set(r) != keys for r in rows):
            sys.exit(f"{table}: 열 불일치 — 격리에만 {sorted(set(cols) - keys)}, 운영에만 {sorted(keys - set(cols))}")
        payload = json.dumps(rows, ensure_ascii=False)
        if DOLLAR in payload:
            sys.exit(f"{table}: 값에 구분자 {DOLLAR} 가 있다")
        ov = overrides.get(table, {})
        col_list = ", ".join(f'"{c}"' for c in cols)
        select_list = ", ".join(ov.get(c, f'r."{c}"') for c in cols)
        stmts.append(
            f"INSERT INTO {table} ({col_list})\n  SELECT {select_list}\n"
            f"  FROM json_populate_recordset(NULL::{table}, {DOLLAR}{payload}{DOLLAR}) AS r;"
        )
        print(f"{table}\t{len(rows)}행")
    contents = json.loads((src / "contents.json").read_text())[0]
    stmts.append(
        f"UPDATE contents SET current_published_version_id = '{contents['current_published_version_id']}' "
        f"WHERE id = '{contents['id']}';"
    )
    stmts.append("COMMIT;" if commit else "ROLLBACK;")
    out = psql("\n".join(stmts) + "\n")
    print(out.strip())
    print("반영함" if commit else "시험 실행(ROLLBACK)")


if __name__ == "__main__":
    main()
