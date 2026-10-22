"""novel revision blocks

Revision ID: 17f49714e5ca
Revises: f89a3d8ed3a8
Create Date: 2026-10-22 09:12:53.403944

화 개정에 문단 블록 칸 둘을 더하고 지금 있는 개정을 채운다.

- `novel_chapter_revisions.block_ids`(uuid[] NULL): 본문을 빈 줄로 나눈 문단마다 하나씩, 같은 순서의 블록 id. 개정이
  바뀌어도 같은 문단을 가리키도록 앞 개정에서 이어받는다.
- `novel_chapter_revisions.content_hash`(TEXT NULL): 문단 배열을 빈 줄 하나로 다시 이은 글의 sha256 hex. 문단 배열이 같으면
  해시도 같다(본문의 문단 사이 공백 차이는 해시에 들지 않는다).

새 코드는 개정을 만들 때 두 칸을 함께 쓴다(`api/novelize/blocks.py` 의 `build_revision`). CHECK 는 두지 않는다 — 문단 수를
SQL 로 같은 규칙으로 셀 수 없어 핵심 불변식(문단 수 = id 수)을 DB 가 지킬 수 없고, 그 불변식은 쓰기 함수 하나가 지킨다.

**백필**(`backfill_block_ids`): 화마다 개정 번호 순서로, `block_ids` 가 NULL 인 행만 채운다 — 다시 돌려도 이미 채운 행은
바꾸지 않는다.
1. 되돌리기 원본(`reverted_from_revision_id`)이 있으면 원본의 id 를 그대로 복제한다(원본은 번호가 작아 먼저 채워진다).
2. 생성·다시 만들기 개정은 전부 새 id 다(새 코드와 같다 — 새 본문을 통째로 받은 개정이라 이을 근거가 없다).
3. 그 밖에는 같은 화의 바로 앞 개정(남아 있는 것 중)과 문단 글자를 순서대로 맞춰(`difflib.SequenceMatcher`) 글자가 같은
   문단만 그 id 를 잇고 나머지는 새 id 다. 첫 개정은 전부 새 id 다.
탈퇴 작가 정리로 되돌리기 원본 칸이 비고 중간 개정이 빠진 화는 3 으로 떨어진다. 운영 개정은 수십 행이라 파이썬 반복으로
1초 안에 끝난다. 칸 추가가 표를 배타 잠금하므로 이 트랜잭션이 끝날 때까지 다른 쓰기가 끼어들지 않는다.

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 두 칸을 모르므로 개정 INSERT 가 둘 다 NULL 로 넣는다(NULL 허용이라
통과). 새 코드는 NULL 행을 응답에서 `blocks: null` 로 내고, 그 위에 새 개정을 쌓을 때는 이을 id 가 없으니 새 id 로 채운다.
겹침 동안 생긴 NULL 행은 두 칸을 NOT NULL 로 좁히는 다음 리비전이 그 첫머리에서 채운다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 떠 있는 API 가 늘 읽고 쓰는 표의 ALTER 라, 오래 걸린 트랜잭션 뒤에서
기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 잠금을 못 잡으면 실패시킨다(다시 돌리면 된다). NULL 칸 추가라 표를 다시 쓰지
않는다.

**downgrade**: 두 칸을 지운다. 블록 id 가 사라지고, 다시 올리면 백필이 새 id 로 채운다(앞과 다른 id 다). 이미지만 되돌릴
때는 downgrade 하지 않는다 — 옛 코드는 두 칸을 모른 채 그대로 돈다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 그래서 문단 나누기(`api/novelize/text.py` 의 `split_paragraphs`)를
아래에 그대로 옮겨 두었다 — 저쪽 규칙이 바뀌어도 이 리비전이 채운 값은 그때의 규칙으로 고정이다.
"""

import hashlib
import logging
import re
import uuid
from collections.abc import Sequence
from difflib import SequenceMatcher

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "17f49714e5ca"
down_revision: str | Sequence[str] | None = "f89a3d8ed3a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_BLANK_LINE = re.compile(r"\n[ \t]*\n")

_SELECT_REVISIONS = sa.text(
    "SELECT id, chapter_id, body, source, reverted_from_revision_id, block_ids"
    " FROM novel_chapter_revisions ORDER BY chapter_id, revision_no"
)
_FILL_REVISION = sa.text(
    "UPDATE novel_chapter_revisions SET block_ids = :ids, content_hash = :hash WHERE id = :id AND block_ids IS NULL"
).bindparams(sa.bindparam("ids", type_=postgresql.ARRAY(sa.Uuid())))


def _split_paragraphs(body: str) -> list[str]:
    return [paragraph.strip() for paragraph in _BLANK_LINE.split(body) if paragraph.strip()]


def _content_hash(paragraphs: list[str]) -> str:
    return hashlib.sha256("\n\n".join(paragraphs).encode("utf-8")).hexdigest()


def _inherit_equal(previous: list[str], previous_ids: list[uuid.UUID], paragraphs: list[str]) -> list[uuid.UUID]:
    ids = [uuid.uuid4() for _ in paragraphs]
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, previous, paragraphs, autojunk=False).get_opcodes():
        if tag == "equal":
            ids[j1:j2] = previous_ids[i1:i2]
    return ids


def backfill_block_ids(connection: sa.Connection) -> int:
    """`block_ids` 가 NULL 인 개정을 채우고, 채운 행 수를 돌려준다."""
    known: dict[uuid.UUID, list[uuid.UUID]] = {}
    previous: dict[uuid.UUID, tuple[list[str], list[uuid.UUID]]] = {}
    filled = 0
    for row in connection.execute(_SELECT_REVISIONS).all():
        paragraphs = _split_paragraphs(row.body)
        ids: list[uuid.UUID] | None = row.block_ids
        if ids is None:
            before = previous.get(row.chapter_id)
            if row.reverted_from_revision_id in known:
                ids = list(known[row.reverted_from_revision_id])
            elif row.source not in ("generate", "regenerate") and before is not None:
                ids = _inherit_equal(before[0], before[1], paragraphs)
            else:
                ids = [uuid.uuid4() for _ in paragraphs]
            connection.execute(_FILL_REVISION, {"ids": ids, "hash": _content_hash(paragraphs), "id": row.id})
            filled += 1
        known[row.id] = ids
        previous[row.chapter_id] = (paragraphs, ids)
    return filled


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("novel_chapter_revisions", sa.Column("block_ids", sa.ARRAY(sa.Uuid()), nullable=True))
    op.add_column("novel_chapter_revisions", sa.Column("content_hash", sa.Text(), nullable=True))
    filled = backfill_block_ids(op.get_bind())
    logger.warning("novel_chapter_revisions: 개정 %d행에 블록 id 와 본문 해시를 채웠다", filled)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("novel_chapter_revisions", "content_hash")
    op.drop_column("novel_chapter_revisions", "block_ids")
