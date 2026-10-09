"""신고 접수 90일 뒤 만료된 노벨·노벨 댓글 신고의 증거 사본을 파기한다.

자체 크론이 없다. 이미 설치된 댓글 증거 매시 크론(`ops.purge_comment_evidence.main`)과 DB 복원
(`ops.restore_db.restore`)이 이 함수를 함께 부른다 — 채팅 응답 신고 증거와 같은 방식이라 VM 에 새 크론을
설치하지 않아도 배포만으로 같은 주기에 돈다. 시스템 Python에서 실행하므로 stdlib와 ops 모듈만 사용한다.

노벨 신고는 신고 시점 공개본 사본(소설 제목·소개·화 제목·본문 앞부분)을, 노벨 댓글 신고는 댓글 본문 사본을
비운다. 신고 사유·처리 상태·시각·처리자·대상 칸은 보존한다. 두 표를 한 문장으로 비운다(한쪽만 비고 실패하는
일이 없게). 두 표는 같은 리비전에서 생겼으므로 하나만 확인하고, 그 표가 없는 이전 백업은 변경하지 않는다.
"""

import subprocess
from datetime import datetime

from ops.pg import run_sh, scalar, shell_quote


def purge_expired_novel_report_evidence(url: str, *, now: datetime) -> int:
    if not scalar("SELECT to_regclass('public.novel_reports')", url=url):
        return 0
    expired = f"evidence_expires_at <= '{now.isoformat()}' AND evidence_purged_at IS NULL"
    sql = (
        "WITH novel AS ("
        "UPDATE novel_reports SET evidence_title = NULL, evidence_synopsis = NULL, "
        "evidence_chapter_title = NULL, evidence_body = NULL, "
        f"evidence_purged_at = '{now.isoformat()}' WHERE {expired} RETURNING id"
        "), comment AS ("
        "UPDATE novel_comment_reports SET evidence_body = NULL, "
        f"evidence_purged_at = '{now.isoformat()}' WHERE {expired} RETURNING id"
        ") SELECT id FROM novel UNION ALL SELECT id FROM comment;"
    )
    result = run_sh(f'psql "$PGURL" -v ON_ERROR_STOP=1 -Atq -c {shell_quote(sql)}', url=url, stdout=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"노벨 신고 증거 파기 실패:\n{result.stderr.decode().strip()}")
    return len([line for line in result.stdout.decode().splitlines() if line.strip()])
