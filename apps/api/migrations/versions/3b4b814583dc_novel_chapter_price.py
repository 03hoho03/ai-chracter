"""novel chapter price

Revision ID: 3b4b814583dc
Revises: 3dd505128e7b
Create Date: 2026-10-19 21:00:00.000000

노벨 화 공개본에 화마다의 가격 칸(`price`, 클로버, 0 = 무료)과 유료에서 무료로 바꾼 시각 칸(`price_changed_at`)을 더한다.
지금까지는 가격을 코드가 화 번호로 정했다(앞 5화 무료, 6화부터 화당 30). 이제 가격은 처음 공개 때 정해 화 공개본에 얼린다 —
6화부터는 작가가 무료로 공개할 수 있고, 무료로 공개한 화는 다시 유료가 되지 않으며, 유료 화는 무료로만 바꿀 수 있다. 화당
가격 상수를 나중에 바꿔도 이미 공개한 화의 값은 그대로다.

**칸**: `price INTEGER NOT NULL DEFAULT 30` + CHECK `price >= 0`. CHECK 에 무료 화 수(5)나 화당 가격(30)을 넣지 않는다 — 상수를
바꿀 때마다 마이그레이션이 필요해지고, 아래의 옛 코드 INSERT 가 앞 화에 30 을 넣는 것이 CHECK 위반(500)이 된다.
`price_changed_at TIMESTAMPTZ NULL` 은 무료로 바꾼 시각이고, 공개 때 정한 값 그대로면 비어 있다.

**백필**: 칸을 더하면 기존 행은 기본값 30 을 받는다. 그 뒤 앞 화(`ordinal <= 5`)를 0 으로 바꾼다(공개 중·거둠·승인 대기 행
모두). `price <> 0` 조건이 있어 다시 돌려도 이미 0 인 행은 건드리지 않는다. 지금 코드의 규칙(앞 5화 무료, 나머지 30)과 같은
값이 되므로 백필 뒤 독자에게 보이는 가격은 바뀌지 않는다.

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 가격 칸을 모른다. 화 공개본 INSERT 는 칸을 넘기지 않아 기본값 30 을
받는다 — 6화 이후는 옛 규칙과 같은 유료이고, 앞 화에도 30 이 들어가지만 새 코드는 앞 화를 이 칸과 무관하게 무료로 판정한다.
옛 코드의 다시 공개 UPDATE 는 가격 칸을 건드리지 않는다. 기본값을 0 으로 두면 겹침 동안 옛 코드가 공개한 6화 이후가 무료로
저장되고, 무료 화는 다시 유료로 바꿀 수 없어 되돌릴 길이 없다. 옛 이미지가 다 내려간 뒤 같은 백필
(`BACKFILL_FREE_CHAPTER_PRICE_SQL`)을 한 번 더 돌리면 그사이 앞 화에 들어간 30 도 0 으로 맞춰진다(읽기 판정은 이미 맞으므로
화면에는 차이가 없다 — 칸 값과 화면을 같게 두려는 정리다).

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 떠 있는 API 가 화 공개본을 늘 읽으므로 오래 걸린 트랜잭션 뒤에서 기다리며 뒤의
요청을 줄 세우지 않게 5초 안에 잠금을 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**downgrade**: 두 칸과 CHECK 를 지운다. 유료에서 무료로 바꾼 화와 6화 이후를 무료로 공개한 화의 기록을 잃는다 — 옛 코드는 화
번호로만 가격을 정하므로 그 화들이 다시 유료로 보인다. 행이 있어도 멈추는 가드는 두지 않는다(테스트 스위트 끝의 `alembic
downgrade base` 가 테스트가 커밋한 행 때문에 깨진다). 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다 — 이
스키마에서 옛 코드가 그대로 돈다. 다만 그때도 무료로 바꾼 화는 옛 코드에게 유료다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3b4b814583dc"
down_revision: str | Sequence[str] | None = "3dd505128e7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

# 앞 무료 화 수는 이 리비전을 쓸 때의 값(5)으로 고정한다 — 마이그레이션은 그때의 규칙을 기록한다.
BACKFILL_FREE_CHAPTER_PRICE_SQL = """
UPDATE novel_chapter_publications SET price = 0
WHERE ordinal <= 5 AND price <> 0
"""


def backfill_free_chapter_price(connection: sa.Connection) -> int:
    """앞 무료 화의 가격 칸을 0 으로 맞추고 바꾼 행 수를 돌려준다."""
    return connection.execute(sa.text(BACKFILL_FREE_CHAPTER_PRICE_SQL)).rowcount


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "novel_chapter_publications", sa.Column("price", sa.Integer(), server_default="30", nullable=False)
    )
    op.add_column(
        "novel_chapter_publications", sa.Column("price_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_novel_chapter_publications_price_nonnegative", "novel_chapter_publications", "price >= 0"
    )
    filled = backfill_free_chapter_price(op.get_bind())
    logger.warning("novel_chapter_publications: 앞 무료 화 %d개의 가격 칸을 0 으로 맞췄다", filled)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ck_novel_chapter_publications_price_nonnegative", "novel_chapter_publications", type_="check")
    op.drop_column("novel_chapter_publications", "price_changed_at")
    op.drop_column("novel_chapter_publications", "price")
