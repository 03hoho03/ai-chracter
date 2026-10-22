"""novel revision blocks not null

Revision ID: 211f81f33be5
Revises: 17f49714e5ca
Create Date: 2026-10-22 14:05:00.000000

화 개정의 블록 칸 둘(`block_ids`·`content_hash`)을 NOT NULL 로 좁힌다. 칸을 더한 앞 리비전(`17f49714e5ca`) 이후의 코드는
개정을 언제나 `api/novelize/blocks.py` 의 `build_revision` 하나로 만들고, 그 함수는 두 칸을 늘 채운다 — 그래서 이 리비전을
배포하는 동안 옛 색으로 도는 앞 리비전 이미지도 이 스키마에서 그대로 돈다(겹침을 끌 필요가 없다).

**첫머리 채우기**(`fill_missing_blocks`): 좁히기 전에 두 칸 중 하나라도 빈 개정을 채운다. 칸을 모르는 이미지(앞 리비전
이전)가 배포 겹침이나 태그 롤백 동안 쓴 개정이 이런 행이다. `block_ids` 가 비었으면 문단마다 새 id 를 매기고(앞 개정에서
잇지 않는다 — 옛 개정끼리의 id 이어짐을 읽는 곳이 없다), 이미 있으면 그대로 둔다. `content_hash` 는 비었으면 계산한다.
문단 나누기와 해시는 앞 리비전 파일의 고정 사본(`_split_paragraphs`·`_content_hash`)을 그대로 불러 쓴다 — 저장된 id 수가
같은 규칙으로 센 문단 수와 맞아야 하기 때문이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 떠 있는 API 가 늘 읽고 쓰는 표의 ALTER 라, 오래 걸린 트랜잭션 뒤에서
기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 잠금을 못 잡으면 실패시킨다(다시 돌리면 된다). NOT NULL 은 표를 한 번
훑지만 다시 쓰지는 않는다. 채우기와 좁히기 사이에 빈 개정이 끼어들면 좁히기가 실패하고 체인 전체가 되돌려진다.

**downgrade**: NOT NULL 만 푼다. 칸과 값은 남아 떠 있는 코드가 그대로 돈다. 앞 리비전 이전 이미지(두 칸을 모르고 NULL 로
쓰는 이미지)로 되돌리기 전에 먼저 이것을 돌린다 — 거꾸로면 그 이미지의 개정 INSERT 가 NOT NULL 위반이다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

import importlib.util
import logging
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "211f81f33be5"
down_revision: str | Sequence[str] | None = "17f49714e5ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_SELECT_MISSING = sa.text(
    "SELECT id, body, block_ids FROM novel_chapter_revisions WHERE block_ids IS NULL OR content_hash IS NULL"
)
_FILL = sa.text("UPDATE novel_chapter_revisions SET block_ids = :ids, content_hash = :hash WHERE id = :id").bindparams(
    sa.bindparam("ids", type_=postgresql.ARRAY(sa.Uuid()))
)


def _blocks_revision_copy() -> tuple[Callable[[str], list[str]], Callable[[list[str]], str]]:
    """앞 리비전 파일의 문단 나누기·해시 사본."""
    (path,) = Path(__file__).parent.glob(f"{down_revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{down_revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    split: Callable[[str], list[str]] = module._split_paragraphs
    digest: Callable[[list[str]], str] = module._content_hash
    return split, digest


def fill_missing_blocks(connection: sa.Connection) -> int:
    """두 칸 중 하나라도 빈 개정을 채우고, 채운 행 수를 돌려준다."""
    split, digest = _blocks_revision_copy()
    rows = connection.execute(_SELECT_MISSING).all()
    for row in rows:
        paragraphs = split(row.body)
        ids = row.block_ids if row.block_ids is not None else [uuid.uuid4() for _ in paragraphs]
        connection.execute(_FILL, {"ids": ids, "hash": digest(paragraphs), "id": row.id})
    return len(rows)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    filled = fill_missing_blocks(op.get_bind())
    logger.warning("novel_chapter_revisions: 블록 칸이 빈 개정 %d행을 채웠다", filled)
    op.alter_column("novel_chapter_revisions", "block_ids", existing_type=postgresql.ARRAY(sa.Uuid()), nullable=False)
    op.alter_column("novel_chapter_revisions", "content_hash", existing_type=sa.Text(), nullable=False)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.alter_column("novel_chapter_revisions", "content_hash", existing_type=sa.Text(), nullable=True)
    op.alter_column("novel_chapter_revisions", "block_ids", existing_type=postgresql.ARRAY(sa.Uuid()), nullable=True)
