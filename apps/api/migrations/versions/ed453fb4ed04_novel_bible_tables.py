"""novel bible tables

Revision ID: ed453fb4ed04
Revises: 02a8ea9563a1
Create Date: 2026-10-30 08:04:25.211116

소설 정본 기억 표 열둘을 만든다 — 코어(확정·슬롯 작업·리비전·개체·근거·만료·검사 결과·각색 후보)와 항목(사건·회상 관계·
사실·지식). 기존 표의 칸·제약은 바꾸지 않는다. 소설·화·개정을 가리키는 FK 는 모두 `ON DELETE CASCADE` 라, 이 표들을 모르는
코드(이 리비전 앞의 이미지)의 소설 삭제·묶음 삭제·숨긴 소설 정리가 FK 위반 없이 지나간다. CHECK·복합 PK·부분 인덱스 조건식은
alembic 1.18.5 의 `alembic check` 가 비교하지 않아 `tests/test_novel_bible_models.py` 의 `IntegrityError` 행위 테스트가
유일한 검증이다. CHECK 의 값 목록은 작성 시점의 `api/novel_bible/ids.py` Literal 사본이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(이 저장소 리비전 관례). 새 표는 비어 있다. FK 를 만들며 `novels`·`novel_chapters`·
`novel_chapter_revisions` 에 SHARE ROW EXCLUSIVE 잠금을 잡아 마이그레이션 트랜잭션이 끝날 때까지 그 표들의 쓰기를 세운다 —
빈 표 열둘을 만드는 짧은 시간이고, 오래 걸린 트랜잭션 때문에 잡지 못하면 5초 뒤 실패한다(다시 돌리면 된다). 읽기는 막지 않는다.

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 이 표들을 모르고 읽지도 쓰지도 않는다. 이 리비전과 함께 나가는
코드도 삭제 경로만 이 표들을 지우고 행을 넣는 코드는 없다.

**downgrade** — 표 열둘을 지운다. 정본 기억 행이 있으면 함께 사라지고, 되살리려면 화를 다시 확정해 추출을 다시 돌려야 한다
(모델 호출 비용이 든다). 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다 — 옛 코드는 이 표들을 읽지 않고, cascade
덕에 옛 삭제 경로도 막히지 않는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ed453fb4ed04'
down_revision: str | Sequence[str] | None = '02a8ea9563a1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('novel_bible_entities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('name_norm', sa.Text(), nullable=False),
    sa.Column('aliases', sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('novel_character_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('character', 'object', 'ability')", name='ck_novel_bible_entities_kind'),
    sa.CheckConstraint('char_length(name_norm) BETWEEN 1 AND 200', name='ck_novel_bible_entities_name'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ux_novel_bible_entities_novel_kind_name', 'novel_bible_entities', ['novel_id', 'kind', 'name_norm'], unique=True)
    op.create_table('novel_bible_commits',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), server_default='chapter_confirm', nullable=False),
    sa.Column('branch', sa.Text(), server_default='canon', nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=True),
    sa.Column('chapter_revision_id', sa.Uuid(), nullable=True),
    sa.Column('content_hash', sa.Text(), nullable=True),
    sa.Column('block_ids_hash', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('base_revision_id', sa.Uuid(), nullable=True),
    sa.Column('source_content_version_id', sa.Uuid(), nullable=True),
    sa.Column('source_input_hash', sa.Text(), nullable=True),
    sa.Column('chat_room_id', sa.Uuid(), nullable=True),
    sa.Column('actor_kind', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('failure_code', sa.Text(), nullable=True),
    sa.Column('cas_losses', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('restarts', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('stage_started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(kind = 'chapter_confirm') = (chapter_id IS NOT NULL AND chapter_revision_id IS NOT NULL AND content_hash IS NOT NULL AND block_ids_hash IS NOT NULL)", name='ck_novel_bible_commits_chapter_ref'),
    sa.CheckConstraint("(status = 'failed') = (failure_code IS NOT NULL)", name='ck_novel_bible_commits_failure_iff_failed'),
    sa.CheckConstraint("actor_kind IN ('admin', 'system', 'user') AND (actor_kind <> 'admin' OR actor_id IS NOT NULL)", name='ck_novel_bible_commits_actor'),
    sa.CheckConstraint("failure_code IS NULL OR failure_code IN ('slot_failed', 'cas_exhausted', 'chapter_gone', 'stalled', 'internal')", name='ck_novel_bible_commits_failure'),
    sa.CheckConstraint("kind IN ('chapter_confirm', 'direct_edit')", name='ck_novel_bible_commits_kind'),
    sa.CheckConstraint("status IN ('pending', 'extracting', 'linking', 'checking', 'committed', 'blocked', 'failed', 'stale')", name='ck_novel_bible_commits_status'),
    sa.CheckConstraint('cas_losses >= 0', name='ck_novel_bible_commits_cas_losses'),
    sa.CheckConstraint('char_length(branch) BETWEEN 1 AND 64', name='ck_novel_bible_commits_branch'),
    sa.CheckConstraint('restarts >= 0', name='ck_novel_bible_commits_restarts'),
    sa.ForeignKeyConstraint(['chapter_id'], ['novel_chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['chapter_revision_id'], ['novel_chapter_revisions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_bible_commits_chapter_id', 'novel_bible_commits', ['chapter_id'], unique=False)
    op.create_index('ix_novel_bible_commits_chapter_revision_id', 'novel_bible_commits', ['chapter_revision_id'], unique=False)
    op.create_index('ix_novel_bible_commits_novel_chapter', 'novel_bible_commits', ['novel_id', 'chapter_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_novel_bible_commits_open', 'novel_bible_commits', ['status', 'stage_started_at'], unique=False, postgresql_where=sa.text("status IN ('pending', 'extracting', 'linking', 'checking')"))
    op.create_index('ux_novel_bible_commits_in_flight', 'novel_bible_commits', ['novel_id', 'branch', 'chapter_id'], unique=True, postgresql_where=sa.text("status IN ('pending', 'extracting', 'linking', 'checking')"))
    op.create_table('novel_bible_findings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('commit_id', sa.Uuid(), nullable=False),
    sa.Column('severity', sa.Text(), nullable=False),
    sa.Column('rule', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("rule IN ('exit_then_appearance', 'use_before_acquisition', 'knowledge_before_fact', 'immutable_attribute_mismatch', 'order_undetermined', 'use_without_acquisition', 'use_after_loss', 'knowledge_source_unclear', 'return_unstated', 'onset_unstated', 'evidence_unverified', 'attribute_surface_differs', 'llm_conflict', 'judge_failed')", name='ck_novel_bible_findings_rule'),
    sa.CheckConstraint("severity IN ('block', 'warning')", name='ck_novel_bible_findings_severity'),
    sa.ForeignKeyConstraint(['commit_id'], ['novel_bible_commits.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_bible_findings_commit', 'novel_bible_findings', ['commit_id'], unique=False)
    op.create_table('novel_bible_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('commit_id', sa.Uuid(), nullable=False),
    sa.Column('slot', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='queued', nullable=False),
    sa.Column('attempts', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('input_hash', sa.Text(), nullable=True),
    sa.Column('cache_key', sa.Text(), nullable=True),
    sa.Column('adapter_id', sa.Text(), nullable=True),
    sa.Column('prompt_set_id', sa.Uuid(), nullable=True),
    sa.Column('proposal', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('reused_from_job_id', sa.Uuid(), nullable=True),
    sa.Column('llm_calls', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('failure_code', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'succeeded') = (proposal IS NOT NULL)", name='ck_novel_bible_jobs_proposal_iff_succeeded'),
    sa.CheckConstraint("failure_code IS NULL OR failure_code IN ('schema_invalid', 'truncated', 'empty', 'blocked', 'llm_error', 'rate_limited', 'cancelled', 'internal', 'expired', 'prompt_missing', 'input_too_large')", name='ck_novel_bible_jobs_failure'),
    sa.CheckConstraint("slot IN ('source', 'events', 'facts', 'knowledge')", name='ck_novel_bible_jobs_slot'),
    sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name='ck_novel_bible_jobs_status'),
    sa.CheckConstraint('attempts >= 0', name='ck_novel_bible_jobs_attempts'),
    sa.ForeignKeyConstraint(['commit_id'], ['novel_bible_commits.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_bible_jobs_cache', 'novel_bible_jobs', ['novel_id', 'slot', 'cache_key'], unique=False, postgresql_where=sa.text("status = 'succeeded'"))
    op.create_index('ix_novel_bible_jobs_queued', 'novel_bible_jobs', ['available_at', 'created_at'], unique=False, postgresql_where=sa.text("status = 'queued'"))
    op.create_index('ix_novel_bible_jobs_running', 'novel_bible_jobs', ['claimed_at'], unique=False, postgresql_where=sa.text("status = 'running'"))
    op.create_index('ux_novel_bible_jobs_commit_slot', 'novel_bible_jobs', ['commit_id', 'slot'], unique=True)
    op.create_table('novel_bible_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('branch', sa.Text(), server_default='canon', nullable=False),
    sa.Column('revision_no', sa.Integer(), nullable=False),
    sa.Column('parent_revision_id', sa.Uuid(), nullable=True),
    sa.Column('commit_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('char_length(branch) BETWEEN 1 AND 64', name='ck_novel_bible_revisions_branch'),
    sa.CheckConstraint('revision_no >= 1', name='ck_novel_bible_revisions_revision_no'),
    sa.ForeignKeyConstraint(['commit_id'], ['novel_bible_commits.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_revision_id'], ['novel_bible_revisions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_bible_revisions_parent', 'novel_bible_revisions', ['parent_revision_id'], unique=False)
    op.create_index('ux_novel_bible_revisions_commit_id', 'novel_bible_revisions', ['commit_id'], unique=True)
    op.create_index('ux_novel_bible_revisions_novel_branch_no', 'novel_bible_revisions', ['novel_id', 'branch', 'revision_no'], unique=True)
    op.create_table('novel_bible_adaptation_candidates',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_revision_id', sa.Uuid(), nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=False),
    sa.Column('fact_key', sa.Uuid(), nullable=False),
    sa.Column('fact_id', sa.Uuid(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='open', nullable=False),
    sa.CheckConstraint("origin IN ('source_canon', 'play')", name='ck_novel_bible_adaptation_candidates_origin'),
    sa.CheckConstraint("status IN ('open', 'accepted', 'rejected')", name='ck_novel_bible_adaptation_candidates_status'),
    sa.ForeignKeyConstraint(['chapter_id'], ['novel_chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_revision_id'], ['novel_bible_revisions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_bible_adaptation_candidates_chapter', 'novel_bible_adaptation_candidates', ['chapter_id'], unique=False)
    op.create_index('ix_novel_bible_adaptation_candidates_created_revision', 'novel_bible_adaptation_candidates', ['created_revision_id'], unique=False)
    op.create_index('ix_novel_bible_adaptation_candidates_novel_key', 'novel_bible_adaptation_candidates', ['novel_id', 'fact_key'], unique=False)
    op.create_table('novel_bible_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_revision_id', sa.Uuid(), nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), server_default='confirmed', nullable=False),
    sa.Column('supersedes_id', sa.Uuid(), nullable=True),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('scene_key', sa.Text(), nullable=True),
    sa.Column('actuality', sa.Text(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('anchor_block_ids', sa.ARRAY(sa.Uuid()), nullable=False),
    sa.Column('present_entity_ids', sa.ARRAY(sa.Uuid()), server_default=sa.text("'{}'::uuid[]"), nullable=False),
    sa.Column('mentioned_entity_ids', sa.ARRAY(sa.Uuid()), server_default=sa.text("'{}'::uuid[]"), nullable=False),
    sa.Column('uses', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.CheckConstraint("actuality IN ('present', 'flashback', 'dream_or_imagined')", name='ck_novel_bible_events_actuality'),
    sa.CheckConstraint("status IN ('confirmed', 'proposed', 'approved_for_revision', 'needs_alignment', 'planned')", name='ck_novel_bible_events_status'),
    sa.CheckConstraint('cardinality(anchor_block_ids) >= 1', name='ck_novel_bible_events_anchor'),
    sa.CheckConstraint('ordinal >= 1', name='ck_novel_bible_events_ordinal'),
    sa.ForeignKeyConstraint(['chapter_id'], ['novel_chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_revision_id'], ['novel_bible_revisions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supersedes_id'], ['novel_bible_events.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_bible_events_created_revision', 'novel_bible_events', ['created_revision_id'], unique=False)
    op.create_index('ix_novel_bible_events_novel_chapter', 'novel_bible_events', ['novel_id', 'chapter_id'], unique=False)
    op.create_index('ix_novel_bible_events_supersedes', 'novel_bible_events', ['supersedes_id'], unique=False)
    op.create_table('novel_bible_evidence',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_revision_id', sa.Uuid(), nullable=False),
    sa.Column('item_table', sa.Text(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=True),
    sa.Column('chapter_revision_id', sa.Uuid(), nullable=True),
    sa.Column('block_id', sa.Uuid(), nullable=True),
    sa.Column('char_start', sa.Integer(), nullable=True),
    sa.Column('char_end', sa.Integer(), nullable=True),
    sa.Column('quote_sha256', sa.Text(), nullable=True),
    sa.Column('chat_room_id', sa.Uuid(), nullable=True),
    sa.Column('chat_memory_fact_id', sa.Uuid(), nullable=True),
    sa.Column('chat_fact_key', sa.Text(), nullable=True),
    sa.Column('chat_message_id', sa.Uuid(), nullable=True),
    sa.Column('content_version_id', sa.Uuid(), nullable=True),
    sa.Column('source_field', sa.Text(), nullable=True),
    sa.Column('keyword_note_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint("item_table IN ('event', 'event_relation', 'fact', 'knowledge', 'adaptation_candidate')", name='ck_novel_bible_evidence_item_table'),
    sa.CheckConstraint("origin <> 'chat_memory' OR (chat_room_id IS NOT NULL AND chat_memory_fact_id IS NOT NULL AND chat_fact_key IS NOT NULL)", name='ck_novel_bible_evidence_chat_memory'),
    sa.CheckConstraint("origin <> 'chat_message' OR chat_message_id IS NOT NULL", name='ck_novel_bible_evidence_chat_message'),
    sa.CheckConstraint("origin <> 'manuscript_block' OR (chapter_id IS NOT NULL AND chapter_revision_id IS NOT NULL AND block_id IS NOT NULL AND char_start IS NOT NULL AND char_end IS NOT NULL AND quote_sha256 IS NOT NULL)", name='ck_novel_bible_evidence_manuscript'),
    sa.CheckConstraint("origin <> 'source_canon' OR (content_version_id IS NOT NULL AND source_field IS NOT NULL AND char_start IS NOT NULL AND char_end IS NOT NULL AND quote_sha256 IS NOT NULL)", name='ck_novel_bible_evidence_source'),
    sa.CheckConstraint("origin IN ('manuscript_block', 'chat_message', 'chat_memory', 'source_canon')", name='ck_novel_bible_evidence_origin'),
    sa.CheckConstraint("source_field IS DISTINCT FROM 'keyword_note' OR keyword_note_id IS NOT NULL", name='ck_novel_bible_evidence_keyword_note'),
    sa.CheckConstraint("source_field IS NULL OR source_field IN ('work_setting', 'keyword_note')", name='ck_novel_bible_evidence_source_field'),
    sa.CheckConstraint('char_start IS NULL OR (char_start >= 0 AND char_end > char_start)', name='ck_novel_bible_evidence_span'),
    sa.ForeignKeyConstraint(['created_revision_id'], ['novel_bible_revisions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_bible_evidence_created_revision', 'novel_bible_evidence', ['created_revision_id'], unique=False)
    op.create_index('ix_novel_bible_evidence_item', 'novel_bible_evidence', ['item_table', 'item_id'], unique=False)
    op.create_index('ix_novel_bible_evidence_novel_chapter', 'novel_bible_evidence', ['novel_id', 'chapter_id'], unique=False, postgresql_where=sa.text("origin = 'manuscript_block'"))
    op.create_table('novel_bible_expirations',
    sa.Column('revision_id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('item_table', sa.Text(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.CheckConstraint("item_table IN ('event', 'event_relation', 'fact', 'knowledge', 'adaptation_candidate')", name='ck_novel_bible_expirations_item_table'),
    sa.CheckConstraint("reason IN ('chapter_replaced', 'edited')", name='ck_novel_bible_expirations_reason'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['revision_id'], ['novel_bible_revisions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('revision_id', 'item_table', 'item_id')
    )
    op.create_index('ix_novel_bible_expirations_item', 'novel_bible_expirations', ['item_table', 'item_id'], unique=False)
    op.create_table('novel_bible_event_relations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_revision_id', sa.Uuid(), nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), server_default='confirmed', nullable=False),
    sa.Column('supersedes_id', sa.Uuid(), nullable=True),
    sa.Column('from_event_id', sa.Uuid(), nullable=False),
    sa.Column('relation', sa.Text(), nullable=False),
    sa.Column('to_anchor_block_id', sa.Uuid(), nullable=False),
    sa.Column('to_chapter_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("relation IN ('before', 'after', 'overlap')", name='ck_novel_bible_event_relations_relation'),
    sa.CheckConstraint("status IN ('confirmed', 'proposed', 'approved_for_revision', 'needs_alignment', 'planned')", name='ck_novel_bible_event_relations_status'),
    sa.ForeignKeyConstraint(['chapter_id'], ['novel_chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_revision_id'], ['novel_bible_revisions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['from_event_id'], ['novel_bible_events.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supersedes_id'], ['novel_bible_event_relations.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_bible_event_relations_created_revision', 'novel_bible_event_relations', ['created_revision_id'], unique=False)
    op.create_index('ix_novel_bible_event_relations_novel_chapter', 'novel_bible_event_relations', ['novel_id', 'chapter_id'], unique=False)
    op.create_index('ix_novel_bible_event_relations_supersedes', 'novel_bible_event_relations', ['supersedes_id'], unique=False)
    op.create_table('novel_bible_facts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_revision_id', sa.Uuid(), nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), server_default='confirmed', nullable=False),
    sa.Column('supersedes_id', sa.Uuid(), nullable=True),
    sa.Column('fact_key', sa.Uuid(), nullable=False),
    sa.Column('subject_entity_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('predicate_norm', sa.Text(), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('value_norm', sa.Text(), nullable=False),
    sa.Column('value_entity_id', sa.Uuid(), nullable=True),
    sa.Column('holds', sa.Boolean(), nullable=False),
    sa.Column('immutable', sa.Boolean(), nullable=False),
    sa.Column('onset', sa.Boolean(), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('valid_from_event_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint("(kind IN ('possession', 'ability', 'relation')) = (value_entity_id IS NOT NULL)", name='ck_novel_bible_facts_value_entity'),
    sa.CheckConstraint("NOT (onset AND scope = 'work')", name='ck_novel_bible_facts_onset'),
    sa.CheckConstraint("NOT immutable OR (kind = 'attribute' AND scope = 'work')", name='ck_novel_bible_facts_immutable'),
    sa.CheckConstraint("holds OR kind IN ('possession', 'ability', 'relation')", name='ck_novel_bible_facts_holds'),
    sa.CheckConstraint("kind <> 'life' OR value_norm IN ('alive', 'dead')", name='ck_novel_bible_facts_life'),
    sa.CheckConstraint("kind <> 'presence' OR value_norm IN ('present', 'departed', 'gone_for_good')", name='ck_novel_bible_facts_presence'),
    sa.CheckConstraint("kind IN ('life', 'presence', 'possession', 'ability', 'attribute', 'relation')", name='ck_novel_bible_facts_kind'),
    sa.CheckConstraint("scope IN ('work', 'from_here', 'scene')", name='ck_novel_bible_facts_scope'),
    sa.CheckConstraint("status IN ('confirmed', 'proposed', 'approved_for_revision', 'needs_alignment', 'planned')", name='ck_novel_bible_facts_status'),
    sa.ForeignKeyConstraint(['chapter_id'], ['novel_chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_revision_id'], ['novel_bible_revisions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['subject_entity_id'], ['novel_bible_entities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supersedes_id'], ['novel_bible_facts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['valid_from_event_id'], ['novel_bible_events.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['value_entity_id'], ['novel_bible_entities.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_bible_facts_created_revision', 'novel_bible_facts', ['created_revision_id'], unique=False)
    op.create_index('ix_novel_bible_facts_novel_chapter', 'novel_bible_facts', ['novel_id', 'chapter_id'], unique=False)
    op.create_index('ix_novel_bible_facts_novel_key', 'novel_bible_facts', ['novel_id', 'fact_key'], unique=False)
    op.create_index('ix_novel_bible_facts_subject', 'novel_bible_facts', ['subject_entity_id'], unique=False)
    op.create_index('ix_novel_bible_facts_supersedes', 'novel_bible_facts', ['supersedes_id'], unique=False)
    op.create_index('ix_novel_bible_facts_valid_from', 'novel_bible_facts', ['valid_from_event_id'], unique=False, postgresql_where=sa.text('valid_from_event_id IS NOT NULL'))
    op.create_index('ix_novel_bible_facts_value_entity', 'novel_bible_facts', ['value_entity_id'], unique=False, postgresql_where=sa.text('value_entity_id IS NOT NULL'))
    op.create_table('novel_bible_knowledge',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('novel_id', sa.Uuid(), nullable=False),
    sa.Column('created_revision_id', sa.Uuid(), nullable=False),
    sa.Column('chapter_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), server_default='confirmed', nullable=False),
    sa.Column('supersedes_id', sa.Uuid(), nullable=True),
    sa.Column('knower_entity_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('fact_key', sa.Uuid(), nullable=False),
    sa.Column('proposition', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('known_since_event_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint("kind IN ('knows', 'believes')", name='ck_novel_bible_knowledge_kind'),
    sa.CheckConstraint("status IN ('confirmed', 'proposed', 'approved_for_revision', 'needs_alignment', 'planned')", name='ck_novel_bible_knowledge_status'),
    sa.ForeignKeyConstraint(['chapter_id'], ['novel_chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_revision_id'], ['novel_bible_revisions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['knower_entity_id'], ['novel_bible_entities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['known_since_event_id'], ['novel_bible_events.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supersedes_id'], ['novel_bible_knowledge.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_novel_bible_knowledge_created_revision', 'novel_bible_knowledge', ['created_revision_id'], unique=False)
    op.create_index('ix_novel_bible_knowledge_knower', 'novel_bible_knowledge', ['knower_entity_id'], unique=False)
    op.create_index('ix_novel_bible_knowledge_known_since', 'novel_bible_knowledge', ['known_since_event_id'], unique=False, postgresql_where=sa.text('known_since_event_id IS NOT NULL'))
    op.create_index('ix_novel_bible_knowledge_novel_chapter', 'novel_bible_knowledge', ['novel_id', 'chapter_id'], unique=False)
    op.create_index('ix_novel_bible_knowledge_novel_key', 'novel_bible_knowledge', ['novel_id', 'fact_key'], unique=False)
    op.create_index('ix_novel_bible_knowledge_supersedes', 'novel_bible_knowledge', ['supersedes_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index('ix_novel_bible_knowledge_supersedes', table_name='novel_bible_knowledge')
    op.drop_index('ix_novel_bible_knowledge_novel_key', table_name='novel_bible_knowledge')
    op.drop_index('ix_novel_bible_knowledge_novel_chapter', table_name='novel_bible_knowledge')
    op.drop_index('ix_novel_bible_knowledge_known_since', table_name='novel_bible_knowledge', postgresql_where=sa.text('known_since_event_id IS NOT NULL'))
    op.drop_index('ix_novel_bible_knowledge_knower', table_name='novel_bible_knowledge')
    op.drop_index('ix_novel_bible_knowledge_created_revision', table_name='novel_bible_knowledge')
    op.drop_table('novel_bible_knowledge')
    op.drop_index('ix_novel_bible_facts_value_entity', table_name='novel_bible_facts', postgresql_where=sa.text('value_entity_id IS NOT NULL'))
    op.drop_index('ix_novel_bible_facts_valid_from', table_name='novel_bible_facts', postgresql_where=sa.text('valid_from_event_id IS NOT NULL'))
    op.drop_index('ix_novel_bible_facts_supersedes', table_name='novel_bible_facts')
    op.drop_index('ix_novel_bible_facts_subject', table_name='novel_bible_facts')
    op.drop_index('ix_novel_bible_facts_novel_key', table_name='novel_bible_facts')
    op.drop_index('ix_novel_bible_facts_novel_chapter', table_name='novel_bible_facts')
    op.drop_index('ix_novel_bible_facts_created_revision', table_name='novel_bible_facts')
    op.drop_table('novel_bible_facts')
    op.drop_index('ix_novel_bible_event_relations_supersedes', table_name='novel_bible_event_relations')
    op.drop_index('ix_novel_bible_event_relations_novel_chapter', table_name='novel_bible_event_relations')
    op.drop_index('ix_novel_bible_event_relations_created_revision', table_name='novel_bible_event_relations')
    op.drop_table('novel_bible_event_relations')
    op.drop_index('ix_novel_bible_expirations_item', table_name='novel_bible_expirations')
    op.drop_table('novel_bible_expirations')
    op.drop_index('ix_novel_bible_evidence_novel_chapter', table_name='novel_bible_evidence', postgresql_where=sa.text("origin = 'manuscript_block'"))
    op.drop_index('ix_novel_bible_evidence_item', table_name='novel_bible_evidence')
    op.drop_index('ix_novel_bible_evidence_created_revision', table_name='novel_bible_evidence')
    op.drop_table('novel_bible_evidence')
    op.drop_index('ix_novel_bible_events_supersedes', table_name='novel_bible_events')
    op.drop_index('ix_novel_bible_events_novel_chapter', table_name='novel_bible_events')
    op.drop_index('ix_novel_bible_events_created_revision', table_name='novel_bible_events')
    op.drop_table('novel_bible_events')
    op.drop_index('ix_novel_bible_adaptation_candidates_novel_key', table_name='novel_bible_adaptation_candidates')
    op.drop_index('ix_novel_bible_adaptation_candidates_created_revision', table_name='novel_bible_adaptation_candidates')
    op.drop_index('ix_novel_bible_adaptation_candidates_chapter', table_name='novel_bible_adaptation_candidates')
    op.drop_table('novel_bible_adaptation_candidates')
    op.drop_index('ux_novel_bible_revisions_novel_branch_no', table_name='novel_bible_revisions')
    op.drop_index('ux_novel_bible_revisions_commit_id', table_name='novel_bible_revisions')
    op.drop_index('ix_novel_bible_revisions_parent', table_name='novel_bible_revisions')
    op.drop_table('novel_bible_revisions')
    op.drop_index('ux_novel_bible_jobs_commit_slot', table_name='novel_bible_jobs')
    op.drop_index('ix_novel_bible_jobs_running', table_name='novel_bible_jobs', postgresql_where=sa.text("status = 'running'"))
    op.drop_index('ix_novel_bible_jobs_queued', table_name='novel_bible_jobs', postgresql_where=sa.text("status = 'queued'"))
    op.drop_index('ix_novel_bible_jobs_cache', table_name='novel_bible_jobs', postgresql_where=sa.text("status = 'succeeded'"))
    op.drop_table('novel_bible_jobs')
    op.drop_index('ix_novel_bible_findings_commit', table_name='novel_bible_findings')
    op.drop_table('novel_bible_findings')
    op.drop_index('ux_novel_bible_commits_in_flight', table_name='novel_bible_commits', postgresql_where=sa.text("status IN ('pending', 'extracting', 'linking', 'checking')"))
    op.drop_index('ix_novel_bible_commits_open', table_name='novel_bible_commits', postgresql_where=sa.text("status IN ('pending', 'extracting', 'linking', 'checking')"))
    op.drop_index('ix_novel_bible_commits_novel_chapter', table_name='novel_bible_commits')
    op.drop_index('ix_novel_bible_commits_chapter_revision_id', table_name='novel_bible_commits')
    op.drop_index('ix_novel_bible_commits_chapter_id', table_name='novel_bible_commits')
    op.drop_table('novel_bible_commits')
    op.drop_index('ux_novel_bible_entities_novel_kind_name', table_name='novel_bible_entities')
    op.drop_table('novel_bible_entities')
