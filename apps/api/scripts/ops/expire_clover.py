"""출석·미션 클로버의 만료를 배치로 정리한다(clover-page-goal-prompt.md CE-7~CE-9).

    # VM 크론 (매일, ops/cron.d/ddona-clover-expire 로 설치)
    cd /opt/ddona/app/apps/api && PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.expire_clover

`clover_lots.expires_at`이 cutoff를 지난 로트를 `remaining = 0`으로 줄이고, 그만큼
`users.clover_balance`를 차감하고, `clover_ledger`에 `expire_burn` 원장 행을 남긴다 — 이 셋이
**한 트랜잭션**이다(CE-9, T-4).

🔴 CE-8 — 차감·잔액 판정 경로(`core/clover.py`)는 만료 필터를 걸지 않는다. **만료의 진실은 이
배치뿐이다.** 배치가 며칠 죽어도 Σ 불변식(`SUM(clover_lots.remaining) == users.clover_balance`)은
깨지지 않는다 — 배치 실행 전에 쓰인 만료분은 이미 `remaining`이 줄어 있어 이중 차감이 없다.

⚠️ **이 파일은 SQLAlchemy/asyncpg/`api.*`를 import하면 안 된다.** 프로덕션 크론은 시스템
`/usr/bin/python3`로 돈다 — `purge_image_requests.py` 상단 경고와 같은 제약이고, 어기면 매일
도는 크론이 import 시점에 죽어 만료 처리가 통째로 멈춘다. `tests/test_ops_production_cron_
importable.py`가 이 제약을 `ast`로 고정한다. DB 접근은 `ops.pg.run_sh`로 컨테이너 안
`psql -Atq`를 부르는 raw SQL이다(구조는 `purge_image_requests.py`를 복제).
"""

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime

from ops.db_url import to_libpq_url
from ops.notify import notify
from ops.pg import run_sh, shell_quote

# clover-page-goal-prompt.md CE-9 — 이 SQL의 확정 사항 셋은 절대 바꾸지 않는다:
#   1. `OLD.remaining AS burned` — `remaining`(갱신 후 값 0)을 쓰면 소멸량이 전부 0이 된다
#      (PostgreSQL 18 `OLD` 문법. 선례: `core/clover.py`의 `burn_all`이 쓰는
#      `RETURNING OLD.clover_balance`).
#   2. 마지막 INSERT는 `deducted` CTE의 `RETURNING`에서 갱신 후 잔액을 직접 받는다 —
#      `JOIN users`로 다시 읽으면 CTE는 문장 시작 시점 스냅샷이라 차감 **전** 잔액이 찍힌다.
#   3. 락 순서는 `users`(1단계) 먼저, `clover_lots`(2단계) 나중 — CE-6의 차감 경로와 같은
#      순서다. 반대로 잡으면 배치와 동시 차감이 겹칠 때 재현 가능한 데드락이다(T-12).
# `{cutoff}`는 스크립트가 시작 시각에 한 번 계산한 고정값이고, 두 문장에 같은 값이 들어간다 —
# 문장 사이에 로트가 새로 만료로 넘어가 1단계에서 안 잠긴 유저가 2단계에 끼어드는 것을 막는다.
_EXPIRE_SQL_TEMPLATE = """
BEGIN;

SELECT u.id
  FROM users u
 WHERE u.id IN (
   SELECT DISTINCT l.user_id FROM clover_lots l
    WHERE l.remaining > 0 AND l.expires_at IS NOT NULL AND l.expires_at <= '{cutoff}'
 )
 ORDER BY u.id
   FOR UPDATE;

WITH expired AS (
  UPDATE clover_lots SET remaining = 0
   WHERE remaining > 0 AND expires_at IS NOT NULL AND expires_at <= '{cutoff}'
   RETURNING user_id, OLD.remaining AS burned
), by_user AS (
  SELECT user_id, sum(burned)::int AS total FROM expired GROUP BY user_id
), deducted AS (
  UPDATE users u SET clover_balance = u.clover_balance - b.total
    FROM by_user b WHERE u.id = b.user_id
    RETURNING u.id AS user_id, u.clover_balance AS balance_after, b.total AS total
)
INSERT INTO clover_ledger (id, user_id, amount, balance_after, kind, created_at)
SELECT gen_random_uuid(), user_id, -total, balance_after, 'expire_burn', now()
  FROM deducted;

COMMIT;
"""


def expire_clover_lots(url: str, *, cutoff: datetime) -> int:
    """`cutoff`(tz-aware)를 지난 로트를 소멸시키고, 영향받은 유저 수를 돌려준다.

    카운트는 1단계(잠금) `SELECT`가 찍는 줄 수로 센다 — 2단계(`WITH...INSERT`)는 goal-prompt
    CE-9 원문 그대로 top-level `RETURNING`이 없어 출력을 안 낸다(`-q`가 명령 태그도 지운다).
    두 문장의 대상 유저 집합은 같은 `cutoff`로 같은 조건을 보므로 1단계 출력이 곧 그 수다.

    `purge_image_requests.py`와 같은 이유로 `-Atq`를 쓴다 — RETURNING 뒤 psql이 찍는 명령
    태그(`INSERT 0 n`)가 `-q` 없이는 결과 줄과 섞인다.
    """
    sql = _EXPIRE_SQL_TEMPLATE.format(cutoff=cutoff.isoformat())
    result = run_sh(f'psql "$PGURL" -Atq -c {shell_quote(sql)}', url=url, stdout=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"클로버 만료 배치 실패:\n{result.stderr.decode().strip()}")
    return len([line for line in result.stdout.decode().splitlines() if line.strip()])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    url = to_libpq_url(os.environ["DATABASE_URL"])
    # clover-page-goal-prompt.md CE-9: 스크립트 시작 시각에 한 번만 계산해 두 SQL 문장에 같은
    # 값을 넘긴다. `expires_at`이 이미 절대시각(timestamptz)이라 KST 변환은 필요 없다.
    affected = expire_clover_lots(url, cutoff=datetime.now(UTC))
    if affected:
        print(f"⏳ clover_lots 만료: {affected}명 잔액 차감")
    else:
        print("만료 대상 없음")
    return 0


def _on_failure(error: Exception) -> int:
    """실패를 stderr에 남기고 Discord로 알린다 — 조용히 실패하면 만료 처리가 아무도 모르게
    멈춘다(`purge_image_requests.py`와 같은 이유)."""
    print(f"실패: {error}", file=sys.stderr)
    notify(f"⏳ ddona clover_lots 만료 배치 실패: {error}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, KeyError) as error:
        sys.exit(_on_failure(error))
