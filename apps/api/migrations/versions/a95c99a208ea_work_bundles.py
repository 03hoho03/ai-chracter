"""work bundles

Revision ID: a95c99a208ea
Revises: 296e34a7182f
Create Date: 2026-10-27 06:23:35.642362

작가가 자기 작품·소설을 사적으로 정리하는 묶음 표 둘을 빈 표로 만든다 — `work_bundles`(묶음)와 `work_bundle_items`(묶음에
든 작품 하나). 소속 행은 `content_id`·`novel_id` 중 정확히 하나만 값을 갖고(CHECK), 두 칸 모두 ON DELETE CASCADE 라 초안·
소설이 하드 삭제되면 소속 행도 DB 가 지운다. 한 묶음 안 중복을 막는 부분 유니크 둘은 작품 id 를 앞 열로 둔다 — 작품·소설을
지울 때 CASCADE 가 `content_id = ?`·`novel_id = ?` 로 소속 행을 찾으므로 그 조회가 인덱스를 타게 하려는 것이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(이 저장소 리비전 관례). 잠금 — 외래키를 가진 표를 만들면 참조되는 표에 참조
무결성 트리거를 다느라 SHARE ROW EXCLUSIVE 를 잡는다. 이 리비전은 `users`·`contents`·`novels` 셋에 이 잠금을 잡고
(빈 DB 에서 같은 DDL 을 트랜잭션 안에서 실행해 `pg_locks` 로 확인했다), 트랜잭션이 커밋될 때까지 쥔다. 읽기와
`SELECT … FOR UPDATE` 는 막지 않지만 세 표의 INSERT·UPDATE·DELETE(채팅 턴의 클로버 잔액 갱신, 작품 자동저장, 소설화 워커의
`updated_at` 갱신 포함)는 그동안 기다린다. 새 표가 비어 있어 검증할 행이 없으므로 잡은 뒤로는 곧 끝난다. 거꾸로 세 표 중
하나에 쓰기 잠금을 쥔 긴 트랜잭션(소설화 워커 등)이 있으면 이 잠금을 5초 안에 못 얻어 마이그레이션이 실패한다 — 바뀐 것
없이 끝나므로 다시 돌리면 된다.

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 이 표를 모르고 읽지도 쓰지도 않는다. 옛 코드의 초안 삭제·소설
삭제도 DB 의 CASCADE 가 소속 행을 지우므로 옛 코드가 몰라도 정합이 맞는다. 옛 코드의 탈퇴는 묶음을 지우지 않는다 — 겹침
동안 새 색에서 묶음을 만든 회원이 같은 겹침 안에 옛 색으로 탈퇴하면 그 묶음이 남는다(겹침은 1분 남짓이라 드물다).

**downgrade** — 두 표를 지운다. 사용자가 만든 묶음(이름과 소속)이 되살릴 수 없이 사라진다. 먼저
`SELECT count(*) FROM work_bundles` 로 행이 있는지 보고, 있으면 사용자 확인 없이 내리지 않는다. 표를 읽고 쓰는 코드를 먼저
내린 뒤에 내린다(반대 순서면 새 코드가 없는 표를 읽어 500).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a95c99a208ea'
down_revision: str | Sequence[str] | None = '296e34a7182f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('work_bundles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_work_bundles_owner_user_id_updated_at', 'work_bundles', ['owner_user_id', 'updated_at'], unique=False)
    op.create_table('work_bundle_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('bundle_id', sa.Uuid(), nullable=False),
    sa.Column('content_id', sa.Uuid(), nullable=True),
    sa.Column('novel_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('num_nonnulls(content_id, novel_id) = 1', name='ck_work_bundle_items_exactly_one_work'),
    sa.ForeignKeyConstraint(['bundle_id'], ['work_bundles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['content_id'], ['contents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_work_bundle_items_bundle_id_created_at', 'work_bundle_items', ['bundle_id', 'created_at'], unique=False)
    op.create_index('ux_work_bundle_items_content_id_bundle_id', 'work_bundle_items', ['content_id', 'bundle_id'], unique=True, postgresql_where=sa.text('content_id IS NOT NULL'))
    op.create_index('ux_work_bundle_items_novel_id_bundle_id', 'work_bundle_items', ['novel_id', 'bundle_id'], unique=True, postgresql_where=sa.text('novel_id IS NOT NULL'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ux_work_bundle_items_novel_id_bundle_id', table_name='work_bundle_items', postgresql_where=sa.text('novel_id IS NOT NULL'))
    op.drop_index('ux_work_bundle_items_content_id_bundle_id', table_name='work_bundle_items', postgresql_where=sa.text('content_id IS NOT NULL'))
    op.drop_index('ix_work_bundle_items_bundle_id_created_at', table_name='work_bundle_items')
    op.drop_table('work_bundle_items')
    op.drop_index('ix_work_bundles_owner_user_id_updated_at', table_name='work_bundles')
    op.drop_table('work_bundles')
