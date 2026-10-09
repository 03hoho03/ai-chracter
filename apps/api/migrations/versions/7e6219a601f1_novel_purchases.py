"""novel purchases

Revision ID: 7e6219a601f1
Revises: ee129f6c416d
Create Date: 2026-10-09 18:59:38.615465

노벨 화 소장 구매를 기록할 자리를 만든다.

- `novel_purchases`: 구매 한 건(구매자·게시자, 소설·화 사본 id·번호·판, 차감 원장, 가격, 삭제 환급 기록). 소설·화 칸은 FK
  없는 사본이라 게시자가 소설을 지우거나 탈퇴해도 행이 남는다.
- `clover_spend_usages`: 사용처 종류에 `novel_read` 를 더하고, 그 소설을 공개한 게시자 칸(`publisher_user_id`)을 더한다.
  CHECK 셋을 손본다 — 종류 목록(`ck_clover_spend_usages_kind`)과 소설 칸 짝(`ck_clover_spend_usages_novel_has_novel`,
  `novel` 과 `novel_read` 모두 소설 칸이 있어야 한다)을 넓혀 바꾸고, 게시자 칸 짝(`novel_read` 에만 있다)을 새로 건다.

CHECK 는 `alembic check` 가 비교하지 않아 행위 테스트(`IntegrityError`)가 유일한 검증이다.

**배포 겹침** — 옛 코드는 구매 테이블을 모르고, 사용처는 `chat`·`novel`·`preview` 만 쓰며 게시자 칸을 모르고(NULL) 넣는다.
바뀐 세 CHECK 는 그 행들을 모두 통과시킨다(넓히는 방향). 옛 코드의 클로버 내역 조회는 원장 `kind` 를 글자로 돌려줄 뿐이라
새 kind 행이 있어도 깨지지 않는다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 사용처 테이블의 CHECK 교체·칸 추가는 그 테이블에 짧은 `ACCESS EXCLUSIVE` 를,
새 FK 들은 `users`·`clover_ledger`·`notifications` 에 짧은 `SHARE ROW EXCLUSIVE` 를 잡는다. 떠 있는 API 가 채팅·소설 차감마다
그 테이블들을 쓰므로, 오래 걸린 트랜잭션 뒤에서 기다리며 뒤의 차감을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체
롤백, 다시 돌리면 된다).

**downgrade** — 구매 행이나 `novel_read` 사용처가 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 구매 행은
구매자가 무엇을 소장했는지의 유일한 기록이고, `novel_read` 사용처는 옛 CHECK 를 통과하지 못한다. 옛 코드로 돌아가기만
하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = '7e6219a601f1'
down_revision: str | Sequence[str] | None = 'ee129f6c416d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_downgradable(conn: Connection) -> None:
    for table, where in (('novel_purchases', 'TRUE'), ('clover_spend_usages', "usage_kind = 'novel_read'")):
        count = conn.execute(sa.text(f"SELECT count(*) FROM {table} WHERE {where}")).scalar_one()
        if count:
            raise RuntimeError(
                f"{table} 에 노벨 구매 {count}행이 있다 — 구매자가 소장한 화의 기록이라 downgrade 로 지우지 않는다. 옛 코드로"
                " 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다)."
            )


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 차감이 CHECK 교체·FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('novel_purchases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('buyer_user_id', sa.Uuid(), nullable=False),
    sa.Column('publisher_user_id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=False),
    sa.Column('chapter_ordinal', sa.Integer(), nullable=False),
    sa.Column('edition', sa.Integer(), nullable=False),
    sa.Column('spend_ledger_id', sa.Uuid(), nullable=False),
    sa.Column('price', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('refunded_amount', sa.Integer(), nullable=True),
    sa.Column('refund_notification_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint('(refunded_at IS NULL) = (refunded_amount IS NULL)', name='ck_novel_purchases_refund_pair'),
    sa.CheckConstraint('chapter_ordinal >= 1 AND edition >= 1', name='ck_novel_purchases_ordinal_edition_positive'),
    sa.CheckConstraint('price > 0', name='ck_novel_purchases_price_positive'),
    sa.CheckConstraint('refund_notification_id IS NULL OR refunded_at IS NOT NULL', name='ck_novel_purchases_notification_after_refund'),
    sa.CheckConstraint('refunded_amount IS NULL OR (refunded_amount >= 0 AND refunded_amount <= price)', name='ck_novel_purchases_refunded_amount_range'),
    sa.ForeignKeyConstraint(['buyer_user_id'], ['users.id'], name='fk_novel_purchases_buyer_user_id'),
    sa.ForeignKeyConstraint(['publisher_user_id'], ['users.id'], name='fk_novel_purchases_publisher_user_id'),
    sa.ForeignKeyConstraint(['refund_notification_id'], ['notifications.id'], name='fk_novel_purchases_refund_notification_id'),
    sa.ForeignKeyConstraint(['spend_ledger_id'], ['clover_ledger.id'], name='fk_novel_purchases_spend_ledger_id'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_purchases_buyer_user_id', 'novel_purchases', ['buyer_user_id'], unique=False)
    op.create_index('ix_novel_purchases_novel_id', 'novel_purchases', ['novel_id'], unique=False)
    op.create_index('ix_novel_purchases_refund_notification_id', 'novel_purchases', ['refund_notification_id'], unique=False)
    op.create_index('ux_novel_purchases_chapter_id_buyer_user_id', 'novel_purchases', ['chapter_id', 'buyer_user_id'], unique=True)
    op.create_index('ux_novel_purchases_spend_ledger_id', 'novel_purchases', ['spend_ledger_id'], unique=True)
    op.add_column('clover_spend_usages', sa.Column('publisher_user_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_clover_spend_usages_publisher_user_id', 'clover_spend_usages', 'users', ['publisher_user_id'], ['id'])
    op.drop_constraint('ck_clover_spend_usages_kind', 'clover_spend_usages', type_='check')
    op.create_check_constraint(
        'ck_clover_spend_usages_kind', 'clover_spend_usages', "usage_kind IN ('chat', 'novel', 'novel_read', 'preview')"
    )
    op.drop_constraint('ck_clover_spend_usages_novel_has_novel', 'clover_spend_usages', type_='check')
    op.create_check_constraint(
        'ck_clover_spend_usages_novel_has_novel',
        'clover_spend_usages',
        "(usage_kind IN ('novel', 'novel_read')) = (novel_id IS NOT NULL)",
    )
    op.create_check_constraint(
        'ck_clover_spend_usages_publisher_for_novel_read',
        'clover_spend_usages',
        "(usage_kind = 'novel_read') = (publisher_user_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    _assert_downgradable(op.get_bind())
    op.drop_constraint('ck_clover_spend_usages_publisher_for_novel_read', 'clover_spend_usages', type_='check')
    op.drop_constraint('ck_clover_spend_usages_novel_has_novel', 'clover_spend_usages', type_='check')
    op.create_check_constraint(
        'ck_clover_spend_usages_novel_has_novel', 'clover_spend_usages', "(usage_kind = 'novel') = (novel_id IS NOT NULL)"
    )
    op.drop_constraint('ck_clover_spend_usages_kind', 'clover_spend_usages', type_='check')
    op.create_check_constraint(
        'ck_clover_spend_usages_kind', 'clover_spend_usages', "usage_kind IN ('chat', 'novel', 'preview')"
    )
    op.drop_constraint('fk_clover_spend_usages_publisher_user_id', 'clover_spend_usages', type_='foreignkey')
    op.drop_column('clover_spend_usages', 'publisher_user_id')
    op.drop_index('ux_novel_purchases_spend_ledger_id', table_name='novel_purchases')
    op.drop_index('ux_novel_purchases_chapter_id_buyer_user_id', table_name='novel_purchases')
    op.drop_index('ix_novel_purchases_refund_notification_id', table_name='novel_purchases')
    op.drop_index('ix_novel_purchases_novel_id', table_name='novel_purchases')
    op.drop_index('ix_novel_purchases_buyer_user_id', table_name='novel_purchases')
    op.drop_table('novel_purchases')
