"""novel v2 batches

Revision ID: 4a4af1ac1df8
Revises: 2494aa0e607e
Create Date: 2026-10-06 23:48:03.926064

소설 구조를 "소설 → 묶음 → 화"로 넓힌다. 생성 한 번이 대화 구간 하나를 여러 화로 나눠 쓸 수 있게 되어, 원문 구간의
주인을 새 `novel_batches` 로 옮기고 기존 `novel_chapters` 행은 화로 그대로 쓴다. 함께 더하는 것: 화의 제목·요약·작가의
말, 소설의 제목·소개·표지·보드 배치, 그리고 새 테이블 넷(인물 카드, 화별 등장 인물, 스냅샷, 읽은 위치). 작업 행
(`novel_jobs`) 변경은 다음 리비전이다.

**옛 이미지로만 되돌려도 돌게 하는 장치** — 이 리비전을 내리지 않고 이미지만 되돌려도 옛 코드가 500 없이 돌아야 한다.
- 화 행의 구간 칸(시작·끝 메시지, 응답 수, 해시)은 묶음 값의 사본으로 남긴다(NOT NULL 그대로). 옛 코드는 이 칸만 읽는다.
- `novel_chapters.batch_id` 는 nullable 이다. 옛 코드의 화 INSERT 는 이 칸을 모른다. 그렇게 생긴 화는 묶음 없이 남고,
  새 코드가 `_backfill_batches` 와 같은 일을 하는 보정으로 다시 채운다(이 함수는 몇 번을 돌려도 결과가 같다).
- 새 NOT NULL 칸은 모두 server_default 를 갖는다(옛 코드의 소설·화 INSERT 가 이 칸들을 모른다).
- 새 자식 테이블(묶음·인물·등장 인물·스냅샷·읽은 위치)은 부모(소설·화)에 `ON DELETE CASCADE` 다 — 이 저장소의 소설
  테이블 "cascade 없음" 관례의 예외다. 옛 코드의 화 삭제·소설 삭제·탈퇴는 이 테이블들을 모르고 작업 → 개정 → 화 → 소설
  순서로만 지우므로, cascade 가 없으면 그 DELETE 가 FK 위반으로 멈춘다. 화 → 묶음 FK 에는 cascade 를 걸지 않는다(묶음
  삭제가 화를 조용히 지우지 않게). 옛 코드는 화를 소설보다 먼저 지우므로 소설 → 묶음 cascade 와 부딪히지 않는다.

**이관**(`_backfill_batches`): 묶음이 없는 화마다 묶음 하나를 만들어(구간 칸 복사, 화 수 목표 1) 그 화의 `batch_id` 를
채우고 `episode_index` 를 0 으로 둔다. 묶음 번호는 그 소설의 기존 묶음 번호 최대값 뒤로 화 번호 순서대로 매긴다 — 처음
이관할 때는 화 번호와 같고, 옛 이미지가 그 사이 새로 만든 화를 나중에 채울 때도 기존 묶음 번호와 겹치지 않는다. PK 는
`gen_random_uuid()` 다(사용자 데이터라 리터럴 UUID 규칙의 대상이 아니다).

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 배포 중에도 떠 있는 API 가 `novel_chapters`·`novels` 를 읽는데, ALTER 가
오래 걸린 트랜잭션 뒤에서 락을 기다리면 그 뒤로 모든 읽기가 줄을 선다. 5초 안에 락을 못 잡으면 마이그레이션이 실패해
배포가 멈추고(체인 전체 롤백) 다시 돌리면 된다. 이 리비전만 올리는 배포는 앞 리비전의 같은 설정을 물려받지 않으므로
여기서 다시 건다.

**downgrade** — 대개 필요 없다(위 장치 덕분에 이미지만 되돌려도 된다). 돌린다면:
- 화가 둘 이상인 묶음이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 그대로 내리면 그 화들이 옛
  화면에서 같은 구간의 장 여러 개로 남고, 묶음을 잃어 다시 묶을 수 없다.
- 화 하나짜리 묶음뿐이어도 다음 데이터는 막지 않고 사라진다: 소설 제목·소개·표지 선택·보드 배치, 화 제목·요약·작가의
  말, 인물 카드와 등장 인물, 스냅샷, 읽은 위치. 화 본문·개정·작업 행은 남는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_novel_v2_migration.py`)가 이 모듈을
`importlib` 로 불러 `_backfill_batches`·`_assert_no_multi_episode_batch` 를 직접 부른다.

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = '4a4af1ac1df8'
down_revision: str | Sequence[str] | None = '2494aa0e607e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 묶음 없는 화마다 묶음 하나. `targets` 는 휘발성 함수(`gen_random_uuid()`)를 담아 한 번만 계산되므로, INSERT 와 UPDATE 가
# 같은 묶음 id 를 본다. 묶음 INSERT 와 화 UPDATE 를 한 문장에 두는 것은 FK 검사가 문장 끝에 돌기 때문에 가능하다.
_BACKFILL_SQL = """
WITH targets AS (
    SELECT
        c.id AS chapter_id,
        gen_random_uuid() AS batch_id,
        c.novel_id,
        COALESCE((SELECT max(b.ordinal) FROM novel_batches b WHERE b.novel_id = c.novel_id), 0)
            + row_number() OVER (PARTITION BY c.novel_id ORDER BY c.ordinal) AS ordinal,
        c.start_message_id,
        c.start_message_created_at,
        c.end_message_id,
        c.end_message_created_at,
        c.assistant_message_count,
        c.source_hash,
        c.created_at
    FROM novel_chapters c
    WHERE c.batch_id IS NULL
),
inserted AS (
    INSERT INTO novel_batches (
        id, novel_id, ordinal, start_message_id, start_message_created_at, end_message_id, end_message_created_at,
        assistant_message_count, source_hash, target_episode_count, created_at
    )
    SELECT
        batch_id, novel_id, ordinal, start_message_id, start_message_created_at, end_message_id, end_message_created_at,
        assistant_message_count, source_hash, 1, created_at
    FROM targets
)
UPDATE novel_chapters c
SET batch_id = t.batch_id, episode_index = 0
FROM targets t
WHERE c.id = t.chapter_id
"""


def _backfill_batches(conn: Connection) -> int:
    """묶음 없는 화마다 묶음 하나를 만들어 잇고, 이은 화 수를 돌려준다. 이미 묶음이 있는 화는 건드리지 않으므로 다시
    돌려도 결과가 같다."""
    return conn.execute(sa.text(_BACKFILL_SQL)).rowcount


def _multi_episode_batch_ids(conn: Connection) -> list[str]:
    rows = conn.execute(
        sa.text(
            "SELECT batch_id FROM novel_chapters WHERE batch_id IS NOT NULL"
            " GROUP BY batch_id HAVING count(*) > 1 ORDER BY batch_id"
        )
    ).scalars()
    return [str(batch_id) for batch_id in rows]


def _assert_no_multi_episode_batch(conn: Connection) -> None:
    """화가 둘 이상인 묶음이 있으면 아무것도 바꾸기 전에 멈춘다(위 docstring 의 downgrade 절)."""
    batch_ids = _multi_episode_batch_ids(conn)
    if batch_ids:
        raise RuntimeError(
            f"화가 둘 이상인 묶음이 {len(batch_ids)}개 있다({', '.join(batch_ids[:10])}"
            f"{' 외' if len(batch_ids) > 10 else ''}). 이대로 내리면 그 화들이 옛 화면에서 같은 구간의 장 여러 개로 남고"
            " 묶음 정보가 사라진다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가"
            " 그대로 돈다). 꼭 내려야 하면 새 코드가 떠 있는 동안 해당 소설에서 그 묶음들을 뒤에서부터 지운 뒤(마지막 묶음"
            " 삭제) 다시 돌린다."
        )


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 읽기가 ALTER 의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('novel_batches',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('start_message_id', sa.Uuid(), nullable=False),
    sa.Column('start_message_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_message_id', sa.Uuid(), nullable=False),
    sa.Column('end_message_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('assistant_message_count', sa.Integer(), nullable=False),
    sa.Column('source_hash', sa.Text(), nullable=False),
    sa.Column('target_episode_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('target_episode_count >= 1', name='ck_novel_batches_target_episode_count_positive'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ux_novel_batches_novel_id_ordinal', 'novel_batches', ['novel_id', 'ordinal'], unique=True)
    op.create_table('novel_characters',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('aliases', sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('memo', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ux_novel_characters_novel_id_name', 'novel_characters', ['novel_id', 'name'], unique=True)
    op.create_table('novel_snapshots',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('manual', 'auto_before_restore')", name='ck_novel_snapshots_kind'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_snapshots_novel_id_created_at', 'novel_snapshots', ['novel_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_table('novel_chapter_characters',
    sa.Column('chapter_id', sa.Uuid(), nullable=False),
    sa.Column('character_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['chapter_id'], ['novel_chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['character_id'], ['novel_characters.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chapter_id', 'character_id')
    )
    op.create_index('ix_novel_chapter_characters_character_id', 'novel_chapter_characters', ['character_id'], unique=False)
    op.create_table('novel_reading_positions',
    sa.Column('chapter_id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('paragraph_index', sa.Integer(), nullable=False),
    sa.Column('paragraph_count', sa.Integer(), nullable=False),
    sa.Column('revision_id', sa.Uuid(), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chapter_id'], ['novel_chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chapter_id')
    )
    op.create_index('ix_novel_reading_positions_novel_id_updated_at', 'novel_reading_positions', ['novel_id', sa.literal_column('updated_at DESC')], unique=False)
    op.create_index('ix_novel_chapter_revisions_reverted_from_revision_id', 'novel_chapter_revisions', ['reverted_from_revision_id'], unique=False)
    op.add_column('novel_chapters', sa.Column('batch_id', sa.Uuid(), nullable=True))
    op.add_column('novel_chapters', sa.Column('episode_index', sa.Integer(), server_default='0', nullable=False))
    op.add_column('novel_chapters', sa.Column('title', sa.Text(), nullable=True))
    op.add_column('novel_chapters', sa.Column('summary', sa.Text(), nullable=True))
    op.add_column('novel_chapters', sa.Column('author_note', sa.Text(), server_default='', nullable=False))
    op.create_index('ix_novel_chapters_batch_id', 'novel_chapters', ['batch_id'], unique=False)
    op.create_foreign_key('novel_chapters_batch_id_fkey', 'novel_chapters', 'novel_batches', ['batch_id'], ['id'])
    op.add_column('novels', sa.Column('title', sa.Text(), nullable=True))
    op.add_column('novels', sa.Column('title_edited_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('novels', sa.Column('synopsis', sa.Text(), server_default='', nullable=False))
    op.add_column('novels', sa.Column('cover_asset_id', sa.Uuid(), nullable=True))
    op.add_column('novels', sa.Column('board_layout', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.create_index('ix_novels_cover_asset_id', 'novels', ['cover_asset_id'], unique=False, postgresql_where=sa.text('cover_asset_id IS NOT NULL'))
    op.create_foreign_key('fk_novels_cover_asset_id', 'novels', 'assets', ['cover_asset_id'], ['id'], ondelete='SET NULL')

    _backfill_batches(op.get_bind())


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    _assert_no_multi_episode_batch(op.get_bind())

    op.drop_constraint('fk_novels_cover_asset_id', 'novels', type_='foreignkey')
    op.drop_index('ix_novels_cover_asset_id', table_name='novels', postgresql_where=sa.text('cover_asset_id IS NOT NULL'))
    op.drop_column('novels', 'board_layout')
    op.drop_column('novels', 'cover_asset_id')
    op.drop_column('novels', 'synopsis')
    op.drop_column('novels', 'title_edited_at')
    op.drop_column('novels', 'title')
    op.drop_index('ix_novel_reading_positions_novel_id_updated_at', table_name='novel_reading_positions')
    op.drop_table('novel_reading_positions')
    op.drop_index('ix_novel_chapter_characters_character_id', table_name='novel_chapter_characters')
    op.drop_table('novel_chapter_characters')
    op.drop_index('ix_novel_snapshots_novel_id_created_at', table_name='novel_snapshots')
    op.drop_table('novel_snapshots')
    op.drop_index('ux_novel_characters_novel_id_name', table_name='novel_characters')
    op.drop_table('novel_characters')
    op.drop_constraint('novel_chapters_batch_id_fkey', 'novel_chapters', type_='foreignkey')
    op.drop_index('ix_novel_chapters_batch_id', table_name='novel_chapters')
    op.drop_column('novel_chapters', 'author_note')
    op.drop_column('novel_chapters', 'summary')
    op.drop_column('novel_chapters', 'title')
    op.drop_column('novel_chapters', 'episode_index')
    op.drop_column('novel_chapters', 'batch_id')
    op.drop_index('ix_novel_chapter_revisions_reverted_from_revision_id', table_name='novel_chapter_revisions')
    op.drop_index('ux_novel_batches_novel_id_ordinal', table_name='novel_batches')
    op.drop_table('novel_batches')
