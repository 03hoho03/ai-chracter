"""신고 접수 90일 뒤 만료된 댓글 원문 증거를 파기한다.

시스템 Python에서 실행하므로 stdlib와 ops 모듈만 사용한다. 신고·조치 메타데이터는
보존하고 본문·스티커·멘션 증거만 비운다. 같은 함수가 DB 복원 뒤 서비스 재공개 전에
만료 증거를 제거한다. 댓글 테이블이 없는 이전 백업은 변경하지 않는다.

채팅 응답 신고 증거도 같은 90일 약속이라 이 크론이 함께 비운다(`ops.purge_chat_report_evidence`) —
별도 크론을 두면 VM 에 따로 설치해야 하는데, 이 크론에 얹으면 배포만으로 같은 주기에 돈다.
"""

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime

from ops.db_url import to_libpq_url
from ops.pg import run_sh, scalar, shell_quote
from ops.purge_chat_report_evidence import purge_expired_chat_report_evidence


def purge_expired_comment_evidence(url: str, *, now: datetime) -> int:
    if not scalar("SELECT to_regclass('public.comment_reports')", url=url):
        return 0
    sql = (
        "UPDATE comment_reports SET evidence_body = NULL, evidence_sticker_id = NULL, "
        "evidence_mention_user_ids = '{}'::uuid[], "
        f"evidence_purged_at = '{now.isoformat()}' "
        f"WHERE evidence_expires_at <= '{now.isoformat()}' AND evidence_purged_at IS NULL "
        "RETURNING id;"
    )
    result = run_sh(f'psql "$PGURL" -v ON_ERROR_STOP=1 -Atq -c {shell_quote(sql)}', url=url, stdout=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"댓글 신고 증거 파기 실패:\n{result.stderr.decode().strip()}")
    return len([line for line in result.stdout.decode().splitlines() if line.strip()])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    url = to_libpq_url(os.environ["DATABASE_URL"])
    now = datetime.now(UTC)
    removed = purge_expired_comment_evidence(url, now=now)
    print(f"댓글 신고 원문 증거 파기: {removed}건")
    removed_chat = purge_expired_chat_report_evidence(url, now=now)
    print(f"채팅 신고 대화 사본 증거 파기: {removed_chat}건")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, KeyError) as error:
        print(f"실패: {error}", file=sys.stderr)
        sys.exit(1)
