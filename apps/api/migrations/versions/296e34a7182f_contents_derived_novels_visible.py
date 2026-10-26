"""contents derived_novels_visible, novels content_id index

Revision ID: 296e34a7182f
Revises: 2ea446be8eb9
Create Date: 2026-10-27 10:00:00.000000

원작 상세가 그 작품으로 만든 공개 소설을 보이게 하는 두 가지를 더한다.

- `contents.derived_novels_visible` — 원작자가 그 목록을 다른 사람에게 숨겼는가(참 = 보임). `NOT NULL DEFAULT true`
  로 붙인다. 상수 기본값이라 Postgres 11 이상에서 표를 다시 쓰지 않고 카탈로그 기본값으로 붙고, 기존 작품은 모두 "보임"
  이 된다(백필 없음). 기본값은 영구히 둔다 — 칸을 모르는 쓰기 경로(옛 이미지의 작품 생성·시드)가 계속 기본값에 기댄다.
- `ix_novels_content_id` — 원작 id 로 소설을 찾는 인덱스. 지금 `novels.content_id` 에는 인덱스가 없어(FK 도 아니다) 그
  조회가 순차 스캔이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(이 저장소 리비전 관례). 잠금 — 일반 `CREATE INDEX`(트랜잭션 안 —
`CONCURRENTLY` 는 이 체인과 맞지 않는다)는 `novels` 에 SHARE 를 잡는다. 읽기는 막지 않고, 쓰기(소설 생성, 소설화
워커의 화 저장과 `updated_at` 갱신, 숨김·삭제 포함)는 인덱스를 다 만들고 이 트랜잭션이 커밋될 때까지 기다린다.
`ADD COLUMN` 은 `contents` 에 ACCESS EXCLUSIVE 를 잡아 커밋까지 `contents` 의 읽기·쓰기를 모두 세운다. 그래서 인덱스를
먼저 만들고 칸을 나중에 붙인다 — 칸 추가는 카탈로그만 고쳐 곧바로 커밋으로 이어지므로 `contents` 가 서 있는 구간이
인덱스 생성 시간만큼 늘지 않는다. 소설화 워커의 긴 트랜잭션이 `novels` 쓰기 잠금을 쥐고 있으면 SHARE 를 5초 안에 못 얻어
마이그레이션이 실패한다 — 바뀐 것 없이 끝나므로 다시 돌리면 된다. 행 수가 작아 인덱스 생성이 짧다는 데 기댄다.

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드의 작품 INSERT 는 칸을 몰라 기본값(보임)이 채우고, 옛 코드는
칸을 읽지도 쓰지도 않는다. 인덱스는 옛 코드의 쿼리 결과를 바꾸지 않는다.

**downgrade** — 칸과 인덱스를 지운다. 칸을 읽는 코드를 먼저 내리고 그 뒤에 내린다(반대 순서면 새 코드가 없는 칸을
읽어 500). 원작자가 고른 숨김은 사라진다 — 다시 올리면 모두 "보임"으로 돌아온다. 먼저
`SELECT count(*) FROM contents WHERE derived_novels_visible IS FALSE` 로 몇 건인지 본다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "296e34a7182f"
down_revision: str | Sequence[str] | None = "2ea446be8eb9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_index("ix_novels_content_id", "novels", ["content_id"], unique=False)
    op.add_column(
        "contents",
        sa.Column("derived_novels_visible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("contents", "derived_novels_visible")
    op.drop_index("ix_novels_content_id", table_name="novels")
