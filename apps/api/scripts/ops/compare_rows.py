"""두 데이터베이스의 테이블별 행 수를 전수 대조한다. 이전이 성공했는지 판정하는 기준이다.

    cd apps/api && PYTHONPATH=scripts uv run --env-file ~/.config/ddona/prod.env \\
        python -m ops.compare_rows --target postgresql://…로컬…

`DATABASE_URL`(원본) vs `--target`(복원본). 하나라도 어긋나면 **exit code 1** 이라 CI·크론에서
그대로 게이트로 쓸 수 있다.

**추정치를 쓰지 않는다.** `pg_stat_user_tables.n_live_tup` 은 빠르지만 VACUUM 시점에 따라 실제와
다르다. 이전 검증에서 "거의 맞음"은 통과가 아니므로 전 테이블에 `count(*)` 를 돌린다.
"""

import argparse
import os
import subprocess
import sys

from ops.db_url import describe, to_libpq_url
from ops.pg import run_sh, shell_quote

# 테이블 목록을 받아 각각 count(*) 를 돌리는 것을 **쿼리 한 번**으로 끝낸다. query_to_xml 이
# 동적 SQL 을 서버 안에서 실행해 주므로, 목록을 받아 왕복하며 29번 더 붙는 것을 피할 수 있다.
COUNT_SQL = """
SELECT table_name,
       (xpath('/row/cnt/text()', query_to_xml(
           format('SELECT count(*) AS cnt FROM %I.%I', table_schema, table_name),
           false, true, '')))[1]::text::bigint AS rows
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name
"""


def counts(url: str) -> dict[str, int]:
    result = run_sh(
        f'psql "$PGURL" -At -F"|" -c {shell_quote(COUNT_SQL)}', url=url, stdout=subprocess.PIPE
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode().strip())
    rows = {}
    for line in result.stdout.decode().splitlines():
        if line.strip():
            name, count = line.rsplit("|", 1)
            rows[name] = int(count)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # 접속 문자열에는 비밀번호가 들어 있고 argv 는 같은 호스트의 다른 프로세스에게 `ps` 로 보인다.
    # 그래서 둘 다 env 로 넘길 수 있게 두고, 플래그는 편의용으로만 남긴다(`restore_db` 와 같은 규약).
    parser.add_argument("--source", default=os.environ.get("DATABASE_URL"), help="원본(기본 $DATABASE_URL)")
    parser.add_argument(
        "--target",
        default=os.environ.get("TARGET_DATABASE_URL"),
        help="대조 대상(기본 $TARGET_DATABASE_URL)",
    )
    args = parser.parse_args()

    if not args.source:
        print("원본이 없다: --source 또는 $DATABASE_URL", file=sys.stderr)
        return 1
    if not args.target:
        print("대상이 없다: --target 또는 $TARGET_DATABASE_URL", file=sys.stderr)
        return 1

    source_url, target_url = to_libpq_url(args.source), to_libpq_url(args.target)
    print(f"원본: {describe(source_url)}")
    print(f"대상: {describe(target_url)}\n")

    source, target = counts(source_url), counts(target_url)

    mismatches = []
    for name in sorted(set(source) | set(target)):
        left, right = source.get(name), target.get(name)
        if left != right:
            mismatches.append((name, left, right))

    total = sum(source.values())
    print(f"원본 테이블 {len(source)}개 / 총 {total:,}행")
    print(f"대상 테이블 {len(target)}개 / 총 {sum(target.values()):,}행\n")

    if not mismatches:
        print(f"✅ 전 테이블 일치 ({len(source)}개)")
        return 0

    print(f"❌ 불일치 {len(mismatches)}건")
    for name, left, right in mismatches:
        print(f"  {name}: 원본 {left if left is not None else '없음'} vs 대상 {right if right is not None else '없음'}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(f"실패: {error}", file=sys.stderr)
        sys.exit(1)
