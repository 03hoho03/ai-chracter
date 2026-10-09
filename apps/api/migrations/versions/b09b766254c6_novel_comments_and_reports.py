"""novel comments and reports

Revision ID: b09b766254c6
Revises: 72a28a37c99e
Create Date: 2026-10-09 21:14:29.515570

노벨 화 댓글과 노벨·노벨 댓글 신고 자리를 만든다.

- `novel_comments`: 노벨 화마다 달리는 댓글(답글 없음). 지우면 행은 남기고 본문을 비운다. 소설·화 FK 는 `ON DELETE
  CASCADE` 다 — 이미지만 옛 판으로 되돌렸을 때 이 표를 모르는 옛 코드의 소설·묶음 삭제·탈퇴가 FK 위반으로 500 이 되지 않게.
- `novel_reports`: 노벨(소설 전체 또는 공개 화) 신고와 신고 시점 공개본 사본(증거, 90일).
- `novel_comment_reports`: 노벨 댓글 신고와 신고 시점 댓글 본문 사본(증거, 90일).

두 신고 표의 소설·화·댓글 칸은 `SET NULL` 이다 — 소설·묶음 삭제와 탈퇴가 대상을 지워도 신고와 증거 사본은 보유 기간 동안
남는다. 사유·상태는 작품·댓글 신고가 이미 쓰는 native enum 타입(`report_reason_category`·`report_status`)을 값 추가 없이 그대로
쓴다(`create_type=False` — 이 리비전은 타입을 만들거나 지우지 않는다).

**배포 겹침** — 새 표 셋만 만들고 기존 표는 건드리지 않는다. 옛 코드는 새 표를 모른다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 새 FK 들이 `users`·`novels`·`novel_chapters`·`admin_users` 에 짧은 `SHARE ROW
EXCLUSIVE` 를 잡는데, 떠 있는 API 가 그 표들을 쓰므로 오래 걸린 트랜잭션 뒤에서 기다리며 뒤의 요청을 줄 세우지 않게 5초 안에
못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**downgrade** 는 댓글과 신고·증거 사본을 버린다. 신고가 남아 있으면 운영자가 처리하지 못한 신고가 사라지므로 행이 있으면
거부한다(먼저 처리하거나 백업 뒤 직접 지운다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b09b766254c6'
down_revision: str | Sequence[str] | None = '72a28a37c99e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 요청이 FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('novel_comments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=False),
    sa.Column('author_user_id', sa.Uuid(), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('moderator_hidden', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('deleted_by', sa.Text(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("deleted_by IS NULL OR deleted_by IN ('author', 'publisher', 'moderator')", name='ck_novel_comments_deleted_by'),
    sa.CheckConstraint('(deleted_at IS NULL) = (body IS NOT NULL)', name='ck_novel_comments_body_until_deleted'),
    sa.CheckConstraint('(deleted_at IS NULL) = (deleted_by IS NULL)', name='ck_novel_comments_deleted_pair'),
    sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], name='fk_novel_comments_author_user_id'),
    sa.ForeignKeyConstraint(['chapter_id'], ['novel_chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_comments_author_user_id', 'novel_comments', ['author_user_id'], unique=False)
    op.create_index('ix_novel_comments_chapter_id_created_at', 'novel_comments', ['chapter_id', sa.literal_column('created_at DESC'), sa.literal_column('id DESC')], unique=False)
    op.create_index('ix_novel_comments_novel_id_created_at', 'novel_comments', ['novel_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_table('novel_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('reporter_user_id', sa.Uuid(), nullable=False),
    sa.Column('publisher_user_id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=True),
    sa.Column('chapter_id', sa.Uuid(), nullable=True),
    sa.Column('chapter_ordinal', sa.Integer(), nullable=True),
    sa.Column('reason_category', postgresql.ENUM('ADULT', 'MINOR_SAFETY', 'COPYRIGHT', 'HATE', 'SPAM', 'OTHER', name='report_reason_category', create_type=False), nullable=False),
    sa.Column('status', postgresql.ENUM('PENDING', 'RESOLVED', 'REJECTED', name='report_status', create_type=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_by_admin_id', sa.Uuid(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('evidence_title', sa.Text(), nullable=True),
    sa.Column('evidence_synopsis', sa.Text(), nullable=True),
    sa.Column('evidence_chapter_title', sa.Text(), nullable=True),
    sa.Column('evidence_body', sa.Text(), nullable=True),
    sa.Column('evidence_expires_at', sa.DateTime(timezone=True), server_default=sa.text("now() + interval '90 days'"), nullable=False),
    sa.Column('evidence_purged_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('chapter_id IS NULL OR chapter_ordinal IS NOT NULL', name='ck_novel_reports_chapter_ordinal'),
    sa.ForeignKeyConstraint(['chapter_id'], ['novel_chapters.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['publisher_user_id'], ['users.id'], name='fk_novel_reports_publisher_user_id'),
    sa.ForeignKeyConstraint(['reporter_user_id'], ['users.id'], name='fk_novel_reports_reporter_user_id'),
    sa.ForeignKeyConstraint(['resolved_by_admin_id'], ['admin_users.id'], name='fk_novel_reports_resolved_by_admin_id'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('novel_id', 'chapter_id', 'reporter_user_id', name='ux_novel_reports_novel_chapter_reporter')
    )
    op.create_index('ix_novel_reports_chapter_id', 'novel_reports', ['chapter_id'], unique=False, postgresql_where=sa.text('chapter_id IS NOT NULL'))
    op.create_index('ix_novel_reports_evidence_expires', 'novel_reports', ['evidence_expires_at'], unique=False)
    op.create_index('ix_novel_reports_status_created', 'novel_reports', ['status', 'created_at', 'id'], unique=False)
    op.create_table('novel_comment_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('reporter_user_id', sa.Uuid(), nullable=False),
    sa.Column('comment_id', sa.Uuid(), nullable=True),
    sa.Column('novel_id', sa.Uuid(), nullable=True),
    sa.Column('comment_author_user_id', sa.Uuid(), nullable=False),
    sa.Column('reason_category', postgresql.ENUM('ADULT', 'MINOR_SAFETY', 'COPYRIGHT', 'HATE', 'SPAM', 'OTHER', name='report_reason_category', create_type=False), nullable=False),
    sa.Column('status', postgresql.ENUM('PENDING', 'RESOLVED', 'REJECTED', name='report_status', create_type=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_by_admin_id', sa.Uuid(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('evidence_body', sa.Text(), nullable=True),
    sa.Column('evidence_expires_at', sa.DateTime(timezone=True), server_default=sa.text("now() + interval '90 days'"), nullable=False),
    sa.Column('evidence_purged_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['comment_author_user_id'], ['users.id'], name='fk_novel_comment_reports_comment_author_user_id'),
    sa.ForeignKeyConstraint(['comment_id'], ['novel_comments.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reporter_user_id'], ['users.id'], name='fk_novel_comment_reports_reporter_user_id'),
    sa.ForeignKeyConstraint(['resolved_by_admin_id'], ['admin_users.id'], name='fk_novel_comment_reports_resolved_by_admin_id'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('comment_id', 'reporter_user_id', name='ux_novel_comment_reports_comment_reporter')
    )
    op.create_index('ix_novel_comment_reports_evidence_expires', 'novel_comment_reports', ['evidence_expires_at'], unique=False)
    op.create_index('ix_novel_comment_reports_novel_id', 'novel_comment_reports', ['novel_id'], unique=False, postgresql_where=sa.text('novel_id IS NOT NULL'))
    op.create_index('ix_novel_comment_reports_status_created', 'novel_comment_reports', ['status', 'created_at', 'id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    _assert_downgradable()
    op.drop_index('ix_novel_comment_reports_status_created', table_name='novel_comment_reports')
    op.drop_index('ix_novel_comment_reports_novel_id', table_name='novel_comment_reports', postgresql_where=sa.text('novel_id IS NOT NULL'))
    op.drop_index('ix_novel_comment_reports_evidence_expires', table_name='novel_comment_reports')
    op.drop_table('novel_comment_reports')
    op.drop_index('ix_novel_reports_status_created', table_name='novel_reports')
    op.drop_index('ix_novel_reports_evidence_expires', table_name='novel_reports')
    op.drop_index('ix_novel_reports_chapter_id', table_name='novel_reports', postgresql_where=sa.text('chapter_id IS NOT NULL'))
    op.drop_table('novel_reports')
    op.drop_index('ix_novel_comments_novel_id_created_at', table_name='novel_comments')
    op.drop_index('ix_novel_comments_chapter_id_created_at', table_name='novel_comments')
    op.drop_index('ix_novel_comments_author_user_id', table_name='novel_comments')
    op.drop_table('novel_comments')


def _assert_downgradable() -> None:
    """신고 행이 있으면 거부한다(모듈 docstring). 댓글은 막지 않는다 — 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만
    되돌리면 되고(이 스키마에서 옛 코드가 그대로 돈다), downgrade 는 댓글을 버리기로 한 사람이 부른다."""
    bind = op.get_bind()
    for table in ("novel_reports", "novel_comment_reports"):
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError(f"{table} 에 행이 {count}개 있어 downgrade 를 거부한다 — 신고를 처리하거나 백업 뒤 직접 지운다.")
