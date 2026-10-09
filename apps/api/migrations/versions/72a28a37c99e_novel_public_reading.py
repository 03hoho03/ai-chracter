"""novel public reading

Revision ID: 72a28a37c99e
Revises: 7e6219a601f1
Create Date: 2026-10-09 20:40:03.575285

노벨 독자 쪽 자리를 만든다.

- `novel_reader_positions`: 노벨 독자가 화마다 읽은 문단(사용자·화 하나에 한 행, 읽던 공개본 판).
- `novel_likes`: 노벨 좋아요(사용자·소설 하나에 한 행).
- `home_novel_curations`: 홈 노벨 섹션에 운영자가 거는 노벨(자리 1~10). 작품 홈 지정 표는 PK 가 native enum 이라 넓히지
  않고 따로 둔다.
- `novel_publications.like_count`·`view_count`: 좋아요 수·조회 수(상대 UPDATE 로만 바꾼다) + 0 이상 CHECK, 최신순·인기순
  목록 인덱스.
- `admin_action_logs.target_novel_id`: 노벨에 한 운영자 조치(홈 노벨 지정)의 대상. 소설이 지워지면 비운다(SET NULL).

새 세 표의 소설·화 FK 는 `ON DELETE CASCADE` 다 — 이미지만 옛 판으로 되돌렸을 때 이 표들을 모르는 옛 코드의 소설 삭제·
탈퇴가 FK 위반으로 500 이 되지 않게. CHECK 와 복합 PK 는 `alembic check` 가 비교하지 않아 행위 테스트(`IntegrityError`)가
유일한 검증이다.

**배포 겹침** — 옛 코드는 새 표를 모르고, `novel_publications` 에 새 칸을 모른 채 INSERT 해도 기본값 0 이 들어간다. 감사
로그 새 칸은 NULL 허용이고, 옛 코드의 감사 로그 조회(회원 상세)는 대상 회원·작품으로만 고르므로 새 칸만 채운 노벨 조치 행은
읽지 않는다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. `admin_action_logs` 칸 추가와 `novel_publications` 칸·CHECK 추가가 그 표에 짧은
`ACCESS EXCLUSIVE` 를, 새 FK 들이 `users`·`novels`·`novel_chapters` 에 짧은 `SHARE ROW EXCLUSIVE` 를 잡는다. 떠 있는 API 가
그 표들을 쓰므로 오래 걸린 트랜잭션 뒤에서 기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체
롤백, 다시 돌리면 된다).

**downgrade** 는 읽은 자리·좋아요·홈 노벨 지정과 수를 버린다. 모두 다시 쌓이는 값이라 막지 않는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '72a28a37c99e'
down_revision: str | Sequence[str] | None = '7e6219a601f1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 요청이 칸 추가·FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('home_novel_curations',
    sa.Column('position', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('position BETWEEN 1 AND 10', name='ck_home_novel_curations_position_range'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('position')
    )
    op.create_index('ux_home_novel_curations_novel_id', 'home_novel_curations', ['novel_id'], unique=True)
    op.create_table('novel_likes',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_novel_likes_user_id'),
    sa.PrimaryKeyConstraint('user_id', 'novel_id')
    )
    op.create_index('ix_novel_likes_novel_id', 'novel_likes', ['novel_id'], unique=False)
    op.create_table('novel_reader_positions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('paragraph_index', sa.Integer(), nullable=False),
    sa.Column('paragraph_count', sa.Integer(), nullable=False),
    sa.Column('edition', sa.Integer(), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('paragraph_index >= 0 AND paragraph_index < paragraph_count AND edition >= 1', name='ck_novel_reader_positions_range'),
    sa.ForeignKeyConstraint(['chapter_id'], ['novel_chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_novel_reader_positions_user_id'),
    sa.PrimaryKeyConstraint('user_id', 'chapter_id')
    )
    op.create_index('ix_novel_reader_positions_chapter_id', 'novel_reader_positions', ['chapter_id'], unique=False)
    op.create_index('ix_novel_reader_positions_novel_id', 'novel_reader_positions', ['novel_id'], unique=False)
    op.create_index('ix_novel_reader_positions_user_id_novel_id_updated_at', 'novel_reader_positions', ['user_id', 'novel_id', sa.literal_column('updated_at DESC')], unique=False)
    op.add_column('admin_action_logs', sa.Column('target_novel_id', sa.Uuid(), nullable=True))
    op.create_index('ix_admin_action_logs_target_novel_id', 'admin_action_logs', ['target_novel_id'], unique=False, postgresql_where=sa.text('target_novel_id IS NOT NULL'))
    op.create_foreign_key('fk_admin_action_logs_target_novel_id', 'admin_action_logs', 'novels', ['target_novel_id'], ['id'], ondelete='SET NULL')
    op.add_column('novel_publications', sa.Column('like_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('novel_publications', sa.Column('view_count', sa.Integer(), server_default='0', nullable=False))
    op.create_check_constraint(
        'ck_novel_publications_counts_nonnegative', 'novel_publications', 'like_count >= 0 AND view_count >= 0'
    )
    op.create_index('ix_novel_publications_like_count', 'novel_publications', [sa.literal_column('like_count DESC'), sa.literal_column('published_at DESC'), sa.literal_column('novel_id DESC')], unique=False)
    op.create_index('ix_novel_publications_published_at', 'novel_publications', [sa.literal_column('published_at DESC'), sa.literal_column('novel_id DESC')], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_novel_publications_published_at', table_name='novel_publications')
    op.drop_index('ix_novel_publications_like_count', table_name='novel_publications')
    op.drop_constraint('ck_novel_publications_counts_nonnegative', 'novel_publications', type_='check')
    op.drop_column('novel_publications', 'view_count')
    op.drop_column('novel_publications', 'like_count')
    op.drop_constraint('fk_admin_action_logs_target_novel_id', 'admin_action_logs', type_='foreignkey')
    op.drop_index('ix_admin_action_logs_target_novel_id', table_name='admin_action_logs', postgresql_where=sa.text('target_novel_id IS NOT NULL'))
    op.drop_column('admin_action_logs', 'target_novel_id')
    op.drop_index('ix_novel_reader_positions_user_id_novel_id_updated_at', table_name='novel_reader_positions')
    op.drop_index('ix_novel_reader_positions_novel_id', table_name='novel_reader_positions')
    op.drop_index('ix_novel_reader_positions_chapter_id', table_name='novel_reader_positions')
    op.drop_table('novel_reader_positions')
    op.drop_index('ix_novel_likes_novel_id', table_name='novel_likes')
    op.drop_table('novel_likes')
    op.drop_index('ux_home_novel_curations_novel_id', table_name='home_novel_curations')
    op.drop_table('home_novel_curations')
