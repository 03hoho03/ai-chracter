"""clover spend usages self play

Revision ID: 10d8d3ed6e0f
Revises: 204652ae3d92
Create Date: 2026-10-09 22:12:23.645729

`clover_spend_usages` 에 자기 플레이 여부 `is_self_play`(지불자 = 작품 소유자)를 더하고 `spender_user_id` 를 NULL 허용으로
바꾼다. 탈퇴가 그 회원이 지불자인 사용처의 지불자를 끊고, 정산은 지불자 대신 저장된 자기 플레이 여부로 판정한다.

- 기존 행은 같은 규칙으로 채운다(작품이 없는 미리보기는 거짓). 그 뒤 NOT NULL 과 기본값 거짓을 건다(아래 배포 겹침).
- CHECK `ck_clover_spend_usages_self_play_has_owner`(자기 플레이면 작품 소유자가 있다)는 alembic 1.18.5 의 `alembic check`
  가 비교하지 않는다 — 행위 테스트가 유일한 검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(이 저장소 리비전 관례). 칸 추가·NOT NULL·CHECK 가 이 테이블에
`ACCESS EXCLUSIVE` 를 잡는데, 떠 있는 API 의 차감이 이 테이블에 쓰므로 오래 걸린 트랜잭션 뒤에서 기다리며 뒤의 차감을 줄
세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 색 중 이 테이블에 쓰는 것은 노벨 구매(`novel_read`) 사용처뿐이고,
그 INSERT 는 `is_self_play` 를 모른다. 그래서 NOT NULL 과 함께 기본값 거짓을 걸어 그 INSERT 가 실패하지 않게 한다. 노벨
구매는 크리에이터 정산 대상이 아니라 거짓이 들어가도 정산 금액이 바뀌지 않는다. 채팅·소설 사용처는 이 리비전과 같은
배포의 새 코드만 쓰고, 새 코드는 언제나 값을 명시한다.

**downgrade** — 지불자가 끊긴(NULL) 행이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 끊긴 지불자는
되살릴 수 없어 NOT NULL 을 다시 걸 수 없고, 그 행을 지우면 작품 소유자의 정산 근거가 사라진다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10d8d3ed6e0f'
down_revision: str | Sequence[str] | None = '204652ae3d92'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 기록 코드와 같은 규칙(지불자 = 작품 소유자). 작품이 없는 미리보기는 비교가 NULL 이라 거짓으로 둔다.
BACKFILL_SELF_PLAY_SQL = (
    "UPDATE clover_spend_usages SET is_self_play = COALESCE(spender_user_id = content_owner_user_id, false)"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column('clover_spend_usages', sa.Column('is_self_play', sa.Boolean(), nullable=True))
    op.execute(BACKFILL_SELF_PLAY_SQL)
    op.alter_column(
        'clover_spend_usages', 'is_self_play', existing_type=sa.Boolean(), nullable=False, server_default=sa.text('false')
    )
    op.alter_column('clover_spend_usages', 'spender_user_id', existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        'ck_clover_spend_usages_self_play_has_owner',
        'clover_spend_usages',
        'NOT is_self_play OR content_owner_user_id IS NOT NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM clover_spend_usages WHERE spender_user_id IS NULL")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"clover_spend_usages 에 지불자가 끊긴 행이 {count}개 있다 — 탈퇴로 끊긴 지불자는 되살릴 수 없어 NOT NULL 을"
            " 다시 걸 수 없다. 사용처를 기록하기 전 판으로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(그 판은"
            " 이 테이블에 쓰지 않아 이 스키마에서 그대로 돈다)."
        )
    op.drop_constraint('ck_clover_spend_usages_self_play_has_owner', 'clover_spend_usages', type_='check')
    op.alter_column('clover_spend_usages', 'spender_user_id', existing_type=sa.Uuid(), nullable=False)
    op.drop_column('clover_spend_usages', 'is_self_play')
