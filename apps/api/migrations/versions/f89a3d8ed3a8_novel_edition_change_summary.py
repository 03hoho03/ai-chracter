"""novel edition change summary

Revision ID: f89a3d8ed3a8
Revises: e9ad8ed93e90
Create Date: 2026-10-19 22:45:01.387668

작가가 공개한 화를 고쳐 다시 낼 때 쓰는 짧은 변경 요약을 판 행에 둔다. 산 사람의 판 고르기가 "산 때의 판"과 "최신 판"에
공개 시각과 함께 이 요약을 보인다.

- `novel_chapter_editions.change_summary`(TEXT NULL): 그 판을 낼 때 작가가 쓴 요약. 첫 판, 정책 스위치가 꺼진 동안 낸 판,
  이 칸이 생기기 전의 판은 비어 있다. 값이 있으면 CHECK `ck_novel_chapter_editions_change_summary_length` 가 1~100자로
  지킨다(요청 검증과 같은 값 — 앞뒤 공백을 던 뒤의 길이다).
- `ck_novel_screenings_flagged_parts` 를 넓힌다: 요약도 공개 화면 글이라 글 심사에 "변경 요약" 자리(`change_summary`)로
  실리고, 걸리면 그 자리가 심사 기록에 남는다.

**요약을 화 공개본이 아니라 판 행에만 두는 이유**: 판 행은 화 공개본을 그대로 베껴 쓴다. 요약을 화 공개본에 두면 다시 공개
UPDATE 가 그 칸을 모르는 옛 이미지에서 지난 판의 요약이 남아 새 판 행으로 베껴진다. 판 행에만 두면 옛 이미지는 그 칸을 몰라
NULL 을 쓴다.

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 판 행의 새 칸을 모르므로 INSERT 가 NULL 로 채운다(NULL 은 길이
CHECK 를 지난다). 넓힌 심사 CHECK 는 옛 값 다섯을 그대로 받는다. 요약은 정책 스위치가 켜졌을 때만 받으므로 처음 배포하는
겹침(스위치 꺼짐) 동안 새 자리 값이 찍힌 심사 행은 생기지 않는다. 켠 뒤 이미지만 되돌리면 그 값이 찍힌 거부 행을 옛 코드가
응답에 실을 때 검증에서 500 이다 — 되돌리기 전 확인은 배포 문서에 있다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 떠 있는 API 가 읽고 쓰는 두 표의 ALTER 라, 오래 걸린 트랜잭션 뒤에서 기다리며
뒤의 요청을 줄 세우지 않게 5초 안에 잠금을 못 잡으면 실패시킨다(다시 돌리면 된다). 칸 추가는 NULL 이라 표를 다시 쓰지 않고,
두 CHECK 는 만들 때 표를 한 번 읽는다(판 행·심사 행은 화 수·공개 요청 수만큼이라 작다).

**downgrade**: 심사 기록의 `change_summary` 자리를 배열에서 빼고(요약만 걸린 거부 행은 짚은 자리가 빈 거부로 남는다 —
행을 지우면 게시자 화면의 최근 심사와 운영자의 심사 기록이 사라진다) 좁은 CHECK 로 되돌린 뒤 요약 칸을 지운다(요약은 영영
사라진다). 이미지만 되돌릴 때는 downgrade 하지 않는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f89a3d8ed3a8"
down_revision: str | Sequence[str] | None = "e9ad8ed93e90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_PARTS = "'novel_title', 'synopsis', 'chapter_title', 'author_note', 'chapter_body'"
_NEW_PARTS = f"{_OLD_PARTS}, 'change_summary'"


def _replace_parts_check(parts: str) -> None:
    op.drop_constraint("ck_novel_screenings_flagged_parts", "novel_screenings", type_="check")
    op.create_check_constraint(
        "ck_novel_screenings_flagged_parts", "novel_screenings", f"flagged_parts <@ ARRAY[{parts}]::text[]"
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("novel_chapter_editions", sa.Column("change_summary", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_novel_chapter_editions_change_summary_length",
        "novel_chapter_editions",
        "char_length(change_summary) BETWEEN 1 AND 100",
    )
    _replace_parts_check(_NEW_PARTS)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "UPDATE novel_screenings SET flagged_parts = array_remove(flagged_parts, 'change_summary')"
        " WHERE 'change_summary' = ANY(flagged_parts)"
    )
    _replace_parts_check(_OLD_PARTS)
    op.drop_column("novel_chapter_editions", "change_summary")
