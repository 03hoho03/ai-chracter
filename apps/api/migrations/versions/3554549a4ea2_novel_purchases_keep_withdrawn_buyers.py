"""novel purchases keep withdrawn buyers

Revision ID: 3554549a4ea2
Revises: 10d8d3ed6e0f
Create Date: 2026-10-10 00:34:51.817753

구매자가 탈퇴해도 노벨 구매 행을 지우지 않고 구매자 칸만 비워 남긴다. 그래서 `novel_purchases.buyer_user_id` 의 NOT NULL 을
푼다. 화·가격·차감 원장·공개 판·시각은 그대로 남아 거래 기록이 되고, 누가 샀는지만 사라진다.

유니크 `(chapter_id, buyer_user_id)` 는 그대로 둔다. Postgres 유니크 인덱스는 NULL 끼리 서로 다르다고 보므로(기본
`NULLS DISTINCT`) 같은 화를 산 탈퇴 구매자가 여럿이어도 행이 함께 남는다.

**배포 겹침** — NOT NULL 을 푸는 것뿐이라 옛 코드의 쓰기는 모두 통과한다. 옛 코드는 탈퇴 때 구매 행을 지우므로 겹침 동안
옛 컨테이너가 처리한 탈퇴는 행을 지운다(그 구매만 가명 보존을 못 한다). 구매자 칸이 빈 행 때문에 옛 코드의 동작이 달라지는
곳은 게시자 삭제 환급과 그 삭제 전 고지다. 환급은 빈 구매자에게 잔액 UPDATE 가 아무 행도 못 잡아 환급하지 않고 그 행에 0 을 돌려줬다고 적는다(500 이
나지 않는다). 소유자 화면의 삭제 전 고지 금액에는 그 행의 가격이 섞여 실제 환급보다 크게 보인다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. `ALTER COLUMN ... DROP NOT NULL` 은 구매 테이블에 짧은 `ACCESS EXCLUSIVE` 를
잡는데, 떠 있는 API 가 구매·열람마다 이 테이블을 읽으므로 오래 걸린 트랜잭션 뒤에서 기다리며 그 읽기를 줄 세우지 않게
5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**downgrade** — 구매자 칸이 빈 행이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. NOT NULL 을 되돌리려면
그 행을 지워야 하는데, 그 행은 보존하기로 한 거래 기록이다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다
(위 배포 겹침과 같은 이유로 옛 코드가 이 스키마에서 돈다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3554549a4ea2'
down_revision: str | Sequence[str] | None = '10d8d3ed6e0f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 구매·열람 읽기가 이 ALTER 의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.alter_column('novel_purchases', 'buyer_user_id', existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM novel_purchases WHERE buyer_user_id IS NULL")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"novel_purchases 에 구매자 칸이 빈 행이 {count}개 있다 — 탈퇴한 구매자의 거래 기록이라 downgrade 로 지우지"
            " 않는다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다)."
        )
    op.alter_column('novel_purchases', 'buyer_user_id', existing_type=sa.Uuid(), nullable=False)
