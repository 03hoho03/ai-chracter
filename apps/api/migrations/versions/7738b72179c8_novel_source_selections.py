"""novel source selections

Revision ID: 7738b72179c8
Revises: c4e1a7d93b20
Create Date: 2026-10-23 12:00:00.000000

소설로 옮길 대화 구간을 사용자가 고른 기록을 담는 표 둘을 더한다.

- `novel_source_selections`: 구간 선택 한 판(소설마다 1부터 오르는 리비전·고를 때 본 방의 마지막 메시지 키·승인 시각, 비면 초안).
  소설 FK 는 `ON DELETE CASCADE`.
- `novel_source_sections`: 그 판에 든 연속 구간 하나(소설에 넣을 `include` 또는 맥락으로만 보낼 `context`, 양 끝 메시지 키·AI 응답
  수·원문 해시). 선택 FK 는 `ON DELETE CASCADE`. 메시지 키에는 FK 가 없다. 고르지 않은 구간은 행이 없다.

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 두 표를 모르고 읽지도 쓰지도 않는다. 소설을 지우는 옛 경로(소설 삭제·탈퇴)는
소설 행을 지울 때 두 표의 행을 CASCADE 로 함께 지운다. 메시지를 지우는 경로(방 삭제·되감기·응답 지우기)는 메시지 키에 FK 가 없어
막히지 않는다. 이 리비전만으로는 행을 쓰는 코드가 없다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 소설 FK 를 만들며 떠 있는 API 가 늘 쓰는 `novels` 에 잠금을 잡으므로, 오래 걸린
트랜잭션 뒤에서 기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(다시 돌리면 된다).

**downgrade**: 구간 선택 행이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다 — 사용자가 고른 구간은 다음 유료 생성의
근거라 조용히 지우지 않는다. 옛 이미지는 이 표들이 있어도 돌므로, 이미지만 되돌리는 데에는 downgrade 가 필요 없다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7738b72179c8"
down_revision: str | Sequence[str] | None = "c4e1a7d93b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "novel_source_selections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("novel_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("room_end_message_id", sa.Uuid(), nullable=False),
        sa.Column("room_end_message_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_novel_source_selections_revision_positive"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_novel_source_selections_novel_id_revision",
        "novel_source_selections",
        ["novel_id", "revision"],
        unique=True,
    )
    op.create_table(
        "novel_source_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("selection_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("start_message_id", sa.Uuid(), nullable=False),
        sa.Column("start_message_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_message_id", sa.Uuid(), nullable=False),
        sa.Column("end_message_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assistant_message_count", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.CheckConstraint("mode IN ('include', 'context')", name="ck_novel_source_sections_mode"),
        sa.CheckConstraint(
            "(start_message_created_at, start_message_id) <= (end_message_created_at, end_message_id)",
            name="ck_novel_source_sections_key_order",
        ),
        sa.CheckConstraint(
            "assistant_message_count >= 0", name="ck_novel_source_sections_assistant_message_count_nonnegative"
        ),
        sa.ForeignKeyConstraint(["selection_id"], ["novel_source_selections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_novel_source_sections_selection_id_start",
        "novel_source_sections",
        ["selection_id", "start_message_created_at", "start_message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM novel_source_selections")).scalar_one()
    if count:
        raise RuntimeError(
            f"구간 선택 {count}행이 남아 있다 — 사용자가 고른 구간(다음 유료 생성의 근거)이라 지우지 않는다. 옛 이미지는 이 표가"
            " 있어도 돌므로 이미지만 되돌린다. 꼭 내려야 하면 그 행들을 기록으로 남긴 뒤 정리하고 다시 돌린다."
        )
    op.drop_index("ux_novel_source_sections_selection_id_start", table_name="novel_source_sections")
    op.drop_table("novel_source_sections")
    op.drop_index("ux_novel_source_selections_novel_id_revision", table_name="novel_source_selections")
    op.drop_table("novel_source_selections")
