"""이미지가 남지 않은 생성 요청(차단·실패)을 90일 뒤 파기한다(image-monitoring-goal-prompt.md IM-7a).

    # VM 크론 (매일, ops/cron.d/ddona-image-request-purge 로 설치)
    cd /opt/ddona/app/apps/api && PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.purge_image_requests

`image_generation_requests`의 `status IN ('blocked', 'failed')` 행은 IM-5 결정으로 프롬프트
원문을 그대로 담는다 — 그중 상당수가 성적·폭력 시도문일 가능성이 높은, 이 서비스에서 가장
민감한 텍스트다. 이미지가 나온 요청(`succeeded`)의 보유기간은 IM-7("이미지와 같은 수명")이
따로 정하고, 이미지가 안 나온 요청은 삭제 트리거가 없어 그대로 두면 탈퇴 전까지 무기한
남는다 — 그래서 `created_at`으로부터 90일 뒤 이 크론이 지운다. **`succeeded`·`pending`은
나이와 무관하게 손대지 않는다.**

**구조는 `vacuum_bugsink.py`에서, DB 삭제 방식은 `backup_db.py`의
`delete_expired_withdrawn_emails`에서 베꼈다** — 이 문서 초고가 하나로 뭉뚱그렸던 것을 조사가
갈랐다. `vacuum_bugsink.py`는 `docker exec ... bugsink-manage vacuum`을 부를 뿐 Postgres에
직접 접속하지 않아 테이블 삭제의 선례가 못 된다. 여기서는 `delete_expired_withdrawn_emails`와
같은 방식(`ops.pg.run_sh`로 컨테이너 안 `psql "$PGURL" -Atq -c <SQL>`)으로 실제 DELETE를 날리고,
삭제 건수는 `.rowcount`(SQLAlchemy 전용) 대신 `DELETE ... RETURNING`이 찍는 줄 수로 센다.

⚠️ **이 파일은 SQLAlchemy/asyncpg/`api.*`를 import하면 안 된다.** 프로덕션 크론은 시스템
`/usr/bin/python3`(boto3만 있고 SQLAlchemy는 없음)로 돈다 — `backup_db.py` 상단 경고와 같은
제약이고, 어기면 매일 도는 크론이 import 시점에 죽어 파기가 통째로 멈춘다(그 사고의 선례가
`backup_db.py`의 만료 `withdrawn_emails` 삭제다). `tests/test_ops_production_cron_importable.py`가
이 제약을 `ast`로 고정한다.
"""

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

from ops.db_url import to_libpq_url
from ops.notify import notify
from ops.pg import run_sh, shell_quote

# image-monitoring-goal-prompt.md IM-7a: 90일. `backup_db.py`의 `WITHDRAWN_EMAIL_BLOCK_PERIOD`와
# 달리 대조할 원본 상수가 없다 — 이 90일은 애플리케이션 코드(`api.core.constants` 등) 어디에도
# 쓰이지 않고 이 크론 자신이 유일한 시행처다(2026-09-16 저장소 전수 확인). 그래서 로컬 상수
# 하나로 두고, 두 값을 대조하는 테스트는 만들지 않는다 — 대조할 짝이 없다.
BLOCKED_OR_FAILED_REQUEST_RETENTION = timedelta(days=90)


def purge_expired_image_requests(url: str, *, now: datetime) -> int:
    """`created_at`이 `now - BLOCKED_OR_FAILED_REQUEST_RETENTION`보다 오래된
    `status IN ('blocked', 'failed')` 행을 지우고 지운 개수를 돌려준다. `succeeded`·`pending`
    행은 이 조건에 걸리지 않는다.

    `delete_expired_withdrawn_emails`(backup_db.py)와 같은 방식(`run_sh`로 컨테이너 안 `psql`을
    부름) — 이 파일은 SQLAlchemy를 import할 수 없다(위 파일 상단 경고).

    ⚠️ **`-q`(quiet)가 없으면 부족하다.** `RETURNING`이 있는 DML 뒤 `psql`은 결과 행과는 별개로
    커맨드 태그(`DELETE n`)를 한 줄 더 찍고 `-t`만으로는 이 태그가 억제되지 않는다 —
    `backup_db.py`가 프로덕션에서 실제로 겪은 함정(0건을 지워도 `DELETE 0` 한 줄이 나와 1건으로
    셈)과 같다. 그래서 처음부터 `-Atq`로 쓴다.
    """
    cutoff = now - BLOCKED_OR_FAILED_REQUEST_RETENTION
    sql = (
        "DELETE FROM image_generation_requests WHERE status IN ('blocked', 'failed') "
        f"AND created_at < '{cutoff.isoformat()}' RETURNING id;"
    )
    result = run_sh(f'psql "$PGURL" -Atq -c {shell_quote(sql)}', url=url, stdout=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"이미지 요청 파기 실패:\n{result.stderr.decode().strip()}")
    return len([line for line in result.stdout.decode().splitlines() if line.strip()])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    url = to_libpq_url(os.environ["DATABASE_URL"])
    removed = purge_expired_image_requests(url, now=datetime.now(UTC))
    if removed:
        print(f"🗑 image_generation_requests 파기: {removed}개 삭제")
    else:
        print("파기 대상 없음")
    return 0


def _on_failure(error: Exception) -> int:
    """실패를 stderr에 남기고 Discord로 알린다 — 조용히 실패하면 "90일 뒤 파기" 약속이 아무도
    모르게 깨진다(`vacuum_bugsink.py`와 같은 이유)."""
    print(f"실패: {error}", file=sys.stderr)
    notify(f"🗑️ ddona image_generation_requests 파기 실패: {error}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, KeyError) as error:
        sys.exit(_on_failure(error))
