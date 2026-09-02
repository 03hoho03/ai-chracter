"""덤프 파일을 대상 Postgres 에 복원한다. 백업이 진짜인지 확인하는 유일한 방법이다.

    # 리허설: 프로덕션 덤프를 로컬 도커 PG 18 에 넣어본다
    cd apps/api && PYTHONPATH=scripts uv run python -m ops.restore_db backups/….dump \\
        --database-url postgresql://postgres:postgres@host.docker.internal:5433/rehearsal

**`--clean --if-exists` 를 쓰지 않는다.** 복원 대상이 비어 있는 것을 전제로 하고, 안 비어 있으면
차라리 실패시킨다 — 운영 DB 를 실수로 덮어쓰는 경로를 스크립트가 제공하지 않는 편이 안전하다.
대상을 비우고 싶으면 사람이 명시적으로 데이터베이스를 다시 만든다.

**소유자·권한 오류가 안 나는 이유**는 덤프를 `--no-owner --no-acl` 로 떴기 때문이다
(`backup_db.py` 참고). 그 옵션 없이 뜬 덤프를 여기 넣으면 롤 이름이 달라 경고가 쏟아진다.
"""

import argparse
import os
import sys
from pathlib import Path

from ops.db_url import describe, to_libpq_url
from ops.pg import run_sh, scalar


def restore(dump_path: Path, url: str) -> None:
    with dump_path.open("rb") as handle:
        # 커스텀 포맷을 stdin 으로 받는다 — 볼륨 마운트가 필요 없다. 대신 병렬(-j)은 못 쓰는데,
        # 10MB 규모에서는 의미 있는 차이가 아니다.
        result = run_sh('pg_restore -d "$PGURL" --no-owner --no-acl', url=url, stdin=handle)
    if result.returncode != 0:
        raise RuntimeError(f"pg_restore 실패:\n{result.stderr.decode().strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("TARGET_DATABASE_URL"),
        help="복원 대상. 생략하면 $TARGET_DATABASE_URL. $DATABASE_URL 을 기본값으로 두지 않는 건 "
        "의도적이다 — 운영 DB 를 기본 대상으로 만들면 언젠가 덮어쓴다.",
    )
    args = parser.parse_args()

    if not args.database_url:
        print("복원 대상이 없다: --database-url 또는 $TARGET_DATABASE_URL", file=sys.stderr)
        return 1
    if not args.dump.exists():
        print(f"덤프 파일이 없다: {args.dump}", file=sys.stderr)
        return 1

    url = to_libpq_url(args.database_url)
    print(f"▶ 복원: {args.dump} → {describe(url)}")
    restore(args.dump, url)

    tables = scalar(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE'",
        url=url,
    )
    revision = scalar("SELECT version_num FROM alembic_version", url=url)
    print(f"✅ 복원 완료 — public 테이블 {tables}개, alembic {revision}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(f"실패: {error}", file=sys.stderr)
        sys.exit(1)
