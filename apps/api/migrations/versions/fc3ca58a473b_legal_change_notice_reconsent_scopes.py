"""legal documents change notice, reconsent scopes

Revision ID: fc3ca58a473b
Revises: 1c4ff252c34a
Create Date: 2026-10-18 20:00:00.000000

법무 문서에 두 칸을 더한다.

**변경 안내(`change_notice_markdown`)**: 그 판에서 무엇이 바뀌었는지 적는 요약이다. 재동의 화면이 약관·처리방침 전문
(운영 현행판 둘을 합치면 5만 자가 넘는다)보다 먼저 보여 준다. 초안에서 쓰고 게시하면 게시본으로 복제된다.

**재동의 범위(`reconsent_scopes`)**: 그 판이 다시 받는 동의 단위(`terms`·`collection`·`transfer`)다. 지금까지는
`requires_reconsent` 불리언 하나라서 처리방침을 고치면 수집·이용 동의와 국외이전 동의를 늘 함께 다시 받아야 했다.
배열로 둔 이유: API 가 같은 모양(`reconsentScopes`)으로 주고받고, 동의 이력 테이블의 동의 단위 칸과 같은 값을 쓴다.
단위별 불리언 셋이면 문서 종류마다 그중 하나나 둘은 뜻 없는 칸이 된다.

**`requires_reconsent` 는 남긴다.** 이 칸을 모르는 이전 이미지가 배포 겹침·이미지 롤백 동안 이 불리언으로 재동의를
판정한다. 두 칸이 어긋나지 않게 CHECK(`requires_reconsent = (cardinality(reconsent_scopes) > 0)`)를 건다. 이전 이미지가
겹침 동안 재동의 판을 게시하면 새 칸이 빈 배열(기본값)이라 이 CHECK 에 걸려 `IntegrityError` 가 나고, 이전 게시 경로는
그것을 "이미 존재하는 버전" 409 로 바꾼다(500 이 아니다). 새 색으로 바뀐 뒤 다시 게시하면 된다. 재동의 없는 게시와 초안
저장은 그대로 된다.

**범위 이관**: 기존 `requires_reconsent = true` 행은 약관이면 `{terms}`, 처리방침이면 `{collection, transfer}` 로 옮긴다
(지금까지 처리방침 재동의는 두 동의를 함께 다시 받았다). 정책 문서에 재동의가 걸린 행이 있으면 옮길 범위가 없어 CHECK 를
만들 수 없으므로 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다(게시 경로가 그런 게시를 422 로 막아 왔다).

**안내 이관(일회성)**: 지금까지 변경 안내는 본문 마크다운의 `## 주요 변경 내용` 절에 들어 있었다. 게시본마다 그 절의
첫 번째 것에서 제목 줄을 뺀 내용(다음 `## ` 제목 앞까지, 앞뒤 공백 정리)을 새 칸에 옮긴다. 절이 없으면 NULL 이다. 본문은
법적 기준본이라 그대로 둔다. 이 추출은 이 리비전에서만 하고 앱은 본문을 파싱하지 않는다.
**초안 행에는 옮기지 않는다.** 운영 초안 본문은 모두 최신 게시본과 같다. 그 절을 초안 칸에 옮기면 다음 게시의 안내가
이미 게시된 판의 안내로 미리 채워져, 재동의 게시의 "안내 필수" 검사를 운영자가 새 안내를 쓰지 않고도 통과한다.
철회본도 옮기지 않는다(시행된 적이 없어 안내를 보여 줄 곳이 없다).

**롤백 순서**: 이 리비전 파일이 있는 이미지로 `downgrade` → 이미지 되돌리기. downgrade 는 두 칸과 CHECK 를 버린다.
쓴 변경 안내는 사라지고(이관분은 본문에 원문이 남아 있다), 동의 단위 하나만 걸었던 판은 `requires_reconsent = true` 로만
남아 이전 코드가 문서 전체 재동의로 읽는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fc3ca58a473b"
down_revision: str | Sequence[str] | None = "1c4ff252c34a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOTICE_HEADING = re.compile(r"^## 주요 변경 내용[ \t]*$", re.MULTILINE)


def extract_change_notice(body_markdown: str) -> str | None:
    """본문의 첫 `## 주요 변경 내용` 절에서 제목 줄을 뺀 내용. 다음 `## ` 제목 앞까지(없으면 문서 끝까지)이고 앞뒤 공백을
    걷는다. 절이 없거나 내용이 비었으면 None."""
    heading = _NOTICE_HEADING.search(body_markdown)
    if heading is None:
        return None
    rest = body_markdown[heading.end() :]
    next_heading = rest.find("\n## ")
    section = rest if next_heading == -1 else rest[:next_heading]
    return section.strip() or None


def upgrade() -> None:
    # 공개 조회·재동의 게이트가 매 요청 이 테이블을 읽는다 — 오래 걸린 트랜잭션 뒤에서 ALTER 락을 기다리며 그 읽기를 줄
    # 세우지 않게, 못 잡으면 마이그레이션이 실패하게 한다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()
    stray = bind.scalar(
        sa.text(
            "SELECT count(*) FROM legal_documents WHERE requires_reconsent AND kind NOT IN ('terms', 'privacy')"
        )
    )
    if stray:
        raise RuntimeError(f"정책 문서에 재동의가 걸린 행이 {stray}건 있다. 옮길 동의 단위가 없어 멈춘다.")

    op.add_column("legal_documents", sa.Column("change_notice_markdown", sa.Text(), nullable=True))
    op.add_column(
        "legal_documents",
        sa.Column("reconsent_scopes", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    )
    op.execute(
        "UPDATE legal_documents SET reconsent_scopes = CASE kind "
        "WHEN 'terms' THEN ARRAY['terms'] ELSE ARRAY['collection', 'transfer'] END "
        "WHERE requires_reconsent"
    )
    op.create_check_constraint(
        "ck_legal_documents_requires_reconsent_matches_scopes",
        "legal_documents",
        "requires_reconsent = (cardinality(reconsent_scopes) > 0)",
    )

    rows = bind.execute(sa.text("SELECT id, body_markdown FROM legal_documents WHERE status = 'published'")).all()
    for document_id, body_markdown in rows:
        notice = extract_change_notice(body_markdown)
        if notice is not None:
            bind.execute(
                sa.text("UPDATE legal_documents SET change_notice_markdown = :notice WHERE id = :id"),
                {"notice": notice, "id": document_id},
            )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ck_legal_documents_requires_reconsent_matches_scopes", "legal_documents", type_="check")
    op.drop_column("legal_documents", "reconsent_scopes")
    op.drop_column("legal_documents", "change_notice_markdown")
