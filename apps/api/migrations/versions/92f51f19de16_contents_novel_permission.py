"""contents novel permission

Revision ID: 92f51f19de16
Revises: 12446c1b0431
Create Date: 2026-10-09 00:12:11.424493

작품 헤더에 소설화 허락 `contents.novel_permission`(허용 안 함 `forbidden` / 나만 보는 소설 `private` / 공개 소설까지
`public`)을 더하고 세 값만 받는 CHECK 를 건다. 기존 행은 상수 기본값 `'private'` 가 채우므로 백필하지 않는다 — 이 칸
전부터 누구나 자기 대화를 소설로 만들 수 있었으므로 기존 작품의 동작이 그대로다. autogenerate 가 CHECK 를 다루지 않아
손으로 추가했다.

**옛 이미지가 이 스키마 위에서 도는 구간** — 옛 코드는 이 칸을 모른다. 작품을 만드는 옛 INSERT(초안 생성·시드)는 칸을
넘기지 않고 기본값이 채우므로 깨지지 않고, 옛 코드는 이 칸을 쓰지 않으므로 CHECK 에도 걸리지 않는다. 옛 코드는 금지
판정을 하지 않으므로 그 구간에 금지 작품의 새 소설이 생길 수 있다(배포 겹침 몇십 초).

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. `contents` 는 모든 목록이 읽는 테이블이라, 칸 추가가 오래 걸린 트랜잭션
뒤에서 락을 기다리는 동안 그 뒤의 읽기가 모두 줄을 선다. 5초 안에 못 잡으면 마이그레이션을 실패시킨다(체인 전체 롤백,
다시 돌리면 된다).

**downgrade** — 기본값이 아닌 행(`novel_permission <> 'private'`)이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로
멈춘다. 작가가 고른 "허용 안 함"을 조용히 잃지 않게 하려는 것이다. 없으면 제약 → 칸 순으로 지운다.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92f51f19de16'
down_revision: str | Sequence[str] | None = '12446c1b0431'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 작품 읽기가 칸 추가의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column('contents', sa.Column('novel_permission', sa.Text(), server_default='private', nullable=False))
    op.create_check_constraint(
        'ck_contents_novel_permission', 'contents', "novel_permission IN ('forbidden', 'private', 'public')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    chosen = op.get_bind().execute(
        sa.text("SELECT count(*) FROM contents WHERE novel_permission <> 'private'")
    ).scalar_one()
    if chosen:
        raise RuntimeError(
            f"contents 에 작가가 고른 소설화 허락(기본값이 아닌 값)이 {chosen}행 있다 — 내리면 그 선택이 사라진다. 옛 코드로"
            " 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다)."
        )
    op.drop_constraint('ck_contents_novel_permission', 'contents', type_='check')
    op.drop_column('contents', 'novel_permission')
