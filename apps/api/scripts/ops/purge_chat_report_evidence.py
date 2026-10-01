"""신고 접수 90일 뒤 만료된 채팅 응답 신고의 대화 사본 증거를 파기한다.

자체 크론이 없다. 이미 설치된 댓글 증거 매시 크론(`ops.purge_comment_evidence.main`)과 DB
복원(`ops.restore_db.restore`)이 이 함수를 함께 부른다 — VM 에 새 크론을 설치하지 않아도 배포만으로
같은 주기에 돈다. 시스템 Python에서 실행하므로 stdlib와 ops 모듈만 사용한다. 신고 사유·메모·처리
메타데이터는 보존하고 신고된 응답과 직전 사용자 메시지 사본만 비운다. 채팅 신고 테이블이 없는
이전 백업은 변경하지 않는다.
"""

import subprocess
from datetime import datetime

from ops.pg import run_sh, scalar, shell_quote


def purge_expired_chat_report_evidence(url: str, *, now: datetime) -> int:
    if not scalar("SELECT to_regclass('public.chat_message_reports')", url=url):
        return 0
    sql = (
        "UPDATE chat_message_reports SET evidence_response = NULL, evidence_user_message = NULL, "
        f"evidence_purged_at = '{now.isoformat()}' "
        f"WHERE evidence_expires_at <= '{now.isoformat()}' AND evidence_purged_at IS NULL "
        "RETURNING id;"
    )
    result = run_sh(f'psql "$PGURL" -v ON_ERROR_STOP=1 -Atq -c {shell_quote(sql)}', url=url, stdout=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"채팅 신고 증거 파기 실패:\n{result.stderr.decode().strip()}")
    return len([line for line in result.stdout.decode().splitlines() if line.strip()])
