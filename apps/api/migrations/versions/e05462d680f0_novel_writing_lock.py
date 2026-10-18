"""novel writing lock

Revision ID: e05462d680f0
Revises: d6abfd9f92ce
Create Date: 2026-10-18 22:00:00.000000

소설에 집필권 잠금 칸 넷을 더하고, 새 작품의 소설화 허락 기본값을 "허용 안 함"으로 바꾸고, 이미 첫 화를 만든 소설을
잠근다.

**칸**: `novels` 에 잠긴 시각(`writing_locked_at`), 그때 원작의 소설화 허락 사본(`writing_lock_permission`, NULL 은 알
수 없음), 그때 원작 버전 id(`writing_lock_content_version_id`, FK 없음 — 원작이 지워져도 소설은 남는다), 출처
(`writing_lock_source`, 첫 화 저장 `first_chapter` / 이 마이그레이션 `backfill`). 넷 다 NULL 허용이고 기본값이 없어 칸
추가는 메타데이터만 바꾼다. CHECK 셋: 허락 값 범위(NULL 통과), 출처 값 범위, 시각과 출처는 함께 있거나 함께 없다.
autogenerate 가 CHECK 를 다루지 않아 손으로 더했다.

**기본값**: `contents.novel_permission` 의 서버 기본값을 `'private'` 에서 `'forbidden'` 으로 바꾼다. 기본값만 바뀌고 이미
있는 작품의 값은 그대로다.

**백필**: 화가 있는 소설은 가장 이른 화 생성 시각으로, 화를 다 지웠어도 성공한 화 생성 작업
(`kind = 'chapter_generate' AND status = 'succeeded'`)이 있는 소설은 그 작업의 끝난 시각으로(둘 다 있으면 이른 쪽) 잠근다.
화 삭제는 작업 행을 지우지 않으므로 성공한 화 생성 작업은 "첫 화가 한 번이라도 저장됐다"의 기록이다. 연쇄 부모
(`chain_generate`)만 성공한 소설·실패 작업만 있는 소설·빈 소설은 잠그지 않는다. 출처는 `backfill`, 허락 사본과 원작 버전은
NULL 이다 — 그때 값을 알 수 없다. 아직 잠기지 않은 소설만 고치므로 다시 돌려도 값이 바뀌지 않는다. 그래서 옛 이미지가 다
내려간 뒤 같은 문장(`BACKFILL_WRITING_LOCK_SQL`)을 한 번 더 돌려, 겹침 구간에 옛 코드가 저장한 첫 화도 잠글 수 있다.

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 잠금 칸을 모른다. 소설 INSERT 는 칸을 넘기지 않아 NULL 이 되고 CHECK
셋을 모두 통과하며, 첫 화를 저장해도 잠금을 쓰지 않는다(위 재실행이 메운다). 옛 코드가 만든 새 작품도 DB 기본값으로
"허용 안 함"이 되는데, 새 정책과 같은 방향이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. `novels`·`contents` 는 매 요청이 읽는 테이블이라, 오래 걸린 트랜잭션 뒤에서
락을 기다리는 동안 그 뒤의 읽기가 모두 줄을 서지 않게 못 잡으면 마이그레이션을 실패시킨다(체인 전체 롤백, 다시 돌리면
된다).

**downgrade**: CHECK 셋과 칸 넷을 지우고 기본값을 `'private'` 로 되돌린다. downgrade 는 잠금 기록을 잃는다 — 첫 화 저장이
남긴 허락·원작 버전 사본이 사라지고, 다시 올리면 백필이 출처 `backfill`·사본 NULL 로만 채운다. 그래도 잠금 행이 있으면
멈추는 가드를 두지 않는 것은, 테스트 세션 끝의 `alembic downgrade base` 가 테스트가 커밋한 잠금 행 하나 때문에 깨지기
때문이다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다). 이미 저장된
`'forbidden'` 값은 되돌리지 않는다 — 작가가 고른 값과 기본값으로 들어간 값을 구별할 수 없다. 그래서 한 리비전 더 내려
`92f51f19de16` 을 지나면 그 downgrade 의 "기본값 아닌 행" 거부가 걸릴 수 있다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e05462d680f0"
down_revision: str | Sequence[str] | None = "d6abfd9f92ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

BACKFILL_WRITING_LOCK_SQL = """
UPDATE novels n
SET writing_locked_at = f.first_at, writing_lock_source = 'backfill'
FROM (
  SELECT novel_id, min(at) AS first_at FROM (
    SELECT novel_id, created_at AS at FROM novel_chapters
    UNION ALL
    SELECT novel_id, finished_at FROM novel_jobs
    WHERE kind = 'chapter_generate' AND status = 'succeeded' AND finished_at IS NOT NULL
  ) s GROUP BY novel_id
) f
WHERE n.id = f.novel_id AND n.writing_locked_at IS NULL
"""


def backfill_writing_locks(connection: sa.Connection) -> int:
    """첫 화를 만든 적이 있는데 아직 잠기지 않은 소설을 잠그고, 잠근 소설 수를 돌려준다."""
    return connection.execute(sa.text(BACKFILL_WRITING_LOCK_SQL)).rowcount


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("novels", sa.Column("writing_locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("novels", sa.Column("writing_lock_permission", sa.Text(), nullable=True))
    op.add_column("novels", sa.Column("writing_lock_content_version_id", sa.Uuid(), nullable=True))
    op.add_column("novels", sa.Column("writing_lock_source", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_novels_writing_lock_permission",
        "novels",
        "writing_lock_permission IN ('forbidden', 'private', 'public')",
    )
    op.create_check_constraint(
        "ck_novels_writing_lock_source", "novels", "writing_lock_source IN ('first_chapter', 'backfill')"
    )
    op.create_check_constraint(
        "ck_novels_writing_lock_complete", "novels", "(writing_locked_at IS NULL) = (writing_lock_source IS NULL)"
    )
    op.execute("ALTER TABLE contents ALTER COLUMN novel_permission SET DEFAULT 'forbidden'")

    locked = backfill_writing_locks(op.get_bind())
    logger.warning("novels: 이미 첫 화를 만든 소설 %d권을 집필권 잠금으로 채웠다", locked)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ck_novels_writing_lock_complete", "novels", type_="check")
    op.drop_constraint("ck_novels_writing_lock_source", "novels", type_="check")
    op.drop_constraint("ck_novels_writing_lock_permission", "novels", type_="check")
    op.drop_column("novels", "writing_lock_source")
    op.drop_column("novels", "writing_lock_content_version_id")
    op.drop_column("novels", "writing_lock_permission")
    op.drop_column("novels", "writing_locked_at")
    op.execute("ALTER TABLE contents ALTER COLUMN novel_permission SET DEFAULT 'private'")
