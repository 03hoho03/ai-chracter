"""소설 정본 기억의 코어 표. 화 개정을 확정하면 확정 행 하나가 생기고, 슬롯마다 작업 행이 추출을 맡는다. 검사를 지나 커밋되면
리비전 하나가 쌓이고 그 리비전에 항목(사건·회상 관계·사실·지식 — `novel_bible_events.py`·`novel_bible_facts.py`·
`novel_bible_knowledge.py`)과 근거·만료·각색 후보가 매달린다. 개체(인물·사물·능력)는 소설에 매달린 이름 행이다.

소설·화·개정을 가리키는 FK 는 모두 `ON DELETE CASCADE` 다. 이미지만 옛 판으로 되돌렸을 때 옛 코드의 소설 삭제·묶음 삭제·숨긴
소설 정리는 이 표들을 모르고 작업 → 개정 → 화 → 소설 순으로만 지우는데, cascade 가 없으면 그 DELETE 가 FK 위반으로 500 이
된다(`novel.py` 모듈 docstring 의 예외와 같은 이유). 새 코드는 cascade 에 기대지 않고 `novelize/deletion.py` 가 자식부터 직접
지운다. 정본 기억 표끼리도 부모가 지워지면 함께 지워지고, 리비전 사슬처럼 다른 확정의 행을 가리키는 칸은 `SET NULL` 이거나
FK 가 없다.

근거의 개정·블록·채팅·원작 참조와 개체의 인물 카드 참조는 FK 가 없는 값이다. 개정은 삭제 경로들이 지우고, 채팅 기억은
되감기·잊기로 사라지고, 인물 카드는 사용자가 합치거나 지운다 — FK 면 그 사용자 경로가 정본 기억 행을 잠그거나 고치게 된다.
근거는 그 원본이 사라져도 남는다.

항목 표(사건·회상 관계·사실·지식·각색 후보)에는 INSERT 만 한다. 바뀐 것은 새 리비전의 새 행과 만료 행으로 나타내고, 행을 고치는
것은 삭제 경로가 일으키는 `SET NULL`·CASCADE 뿐이다. 모든 표가 `novel_id` 를 갖는다 — 소설 삭제와 조회의 기준이다.

종류·상태처럼 값이 정해진 칸은 Text + Literal 이고 DB 범위는 CHECK 가 막는다. 값 목록은 `novel_bible/ids.py` 의 Literal 에서
만든다. 🔴 `alembic check` 는 CHECK 제약·복합 PK·부분 인덱스 조건식을 비교하지 않는다 — 검증은
`tests/test_novel_bible_models.py` 의 `IntegrityError` 행위 테스트가 유일하다."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.models.novel import _sql_in_list
from api.novel_bible.ids import (
    ActorKind,
    AdaptationOrigin,
    AdaptationStatus,
    CommitFailure,
    CommitKind,
    CommitStatus,
    EntityKind,
    EvidenceOrigin,
    ExpirationReason,
    FindingRule,
    FindingSeverity,
    ItemStatus,
    ItemTable,
    JobFailure,
    JobStatus,
    SlotId,
    SourceField,
)

# 끝나지 않은 확정. 화마다 이 상태의 확정은 하나뿐이고(부분 유니크), 준비된 확정 고르기와 멈춘 확정 정리가 이 상태만 본다.
_COMMIT_IN_FLIGHT = "status IN ('pending', 'extracting', 'linking', 'checking')"


class NovelBibleCommit(Base):
    """정본 기억 입구를 한 번 지날 때마다 한 행 — 화 개정 확정(`chapter_confirm`)이면 그 화·개정과 본문 해시·블록 id 해시의
    사본을 갖는다. 추출 → 연결 → 검사를 거쳐 `committed`(리비전이 생김)·`blocked`(차단 검사 결과)·`failed`·`stale`(같은 화에 새
    확정이 들어와 밀려남) 중 하나로 끝난다.

    `base_revision_id` 는 연결을 시작할 때의 정본 기억 머리이고 FK 가 없다 — 커밋 때 지금 머리와 비교하는 값일 뿐이라, 그
    리비전이 지워지면 비교가 지는 쪽으로 간다. 원작 버전·방·어드민 칸도 FK 가 없다(원작 사본 칸과 같은 이유 — 그쪽이 지워져도
    확정 기록은 남는다). 어드민 조치 기록 표의 종류 CHECK 를 넓히지 않으려고 누가 확정했는지를 이 행의 `actor_*` 에 둔다."""

    __tablename__ = "novel_bible_commits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[CommitKind] = mapped_column(Text, nullable=False, server_default="chapter_confirm")
    branch: Mapped[str] = mapped_column(Text, nullable=False, server_default="canon")
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_chapters.id", ondelete="CASCADE"), nullable=True
    )
    chapter_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_chapter_revisions.id", ondelete="CASCADE"), nullable=True
    )
    # 개정의 본문 해시 사본(본문 글만)과, 개정의 블록 id 를 순서대로 이은 문자열의 sha256.
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    block_ids_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CommitStatus] = mapped_column(Text, nullable=False)
    base_revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    source_content_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    source_input_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    chat_room_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor_kind: Mapped[ActorKind] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    failure_code: Mapped[CommitFailure | None] = mapped_column(Text, nullable=True)
    # 커밋 때 머리 비교에서 진 횟수와, 멈춘 확정 정리가 연결·검사를 추출 끝 상태로 되돌린 횟수.
    cas_losses: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    restarts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    stage_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 화·개정 인덱스는 화·개정 DELETE 때 FK 검사용이다.
    __table_args__ = (
        CheckConstraint(f"kind IN ({_sql_in_list(CommitKind)})", name="ck_novel_bible_commits_kind"),
        CheckConstraint(f"status IN ({_sql_in_list(CommitStatus)})", name="ck_novel_bible_commits_status"),
        CheckConstraint("char_length(branch) BETWEEN 1 AND 64", name="ck_novel_bible_commits_branch"),
        # 화 확정은 화·개정·두 해시를 모두 갖고, 다른 종류는 하나도 갖지 않는다.
        CheckConstraint(
            "(kind = 'chapter_confirm') = (chapter_id IS NOT NULL AND chapter_revision_id IS NOT NULL"
            " AND content_hash IS NOT NULL AND block_ids_hash IS NOT NULL)",
            name="ck_novel_bible_commits_chapter_ref",
        ),
        CheckConstraint(
            f"actor_kind IN ({_sql_in_list(ActorKind)}) AND (actor_kind <> 'admin' OR actor_id IS NOT NULL)",
            name="ck_novel_bible_commits_actor",
        ),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({_sql_in_list(CommitFailure)})",
            name="ck_novel_bible_commits_failure",
        ),
        CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL)", name="ck_novel_bible_commits_failure_iff_failed"
        ),
        CheckConstraint("cas_losses >= 0", name="ck_novel_bible_commits_cas_losses"),
        CheckConstraint("restarts >= 0", name="ck_novel_bible_commits_restarts"),
        # 화마다 진행 중 확정은 하나 — 새 확정이 들어오면 앞 것을 `stale` 로 돌린 뒤 넣는다.
        Index(
            "ux_novel_bible_commits_in_flight",
            "novel_id",
            "branch",
            "chapter_id",
            unique=True,
            postgresql_where=text(_COMMIT_IN_FLIGHT),
        ),
        Index("ix_novel_bible_commits_novel_chapter", "novel_id", "chapter_id", created_at.desc()),
        Index("ix_novel_bible_commits_chapter_revision_id", "chapter_revision_id"),
        Index("ix_novel_bible_commits_chapter_id", "chapter_id"),
        # 준비된 확정 고르기와 멈춘 확정 정리용.
        Index("ix_novel_bible_commits_open", "status", "stage_started_at", postgresql_where=text(_COMMIT_IN_FLIGHT)),
    )


class NovelBibleJob(Base):
    """확정 하나의 슬롯 하나 = 한 행. 검증을 통과한 추출 결과를 `proposal` 에 두었다가 커밋이 정본 표에 옮긴다.

    `input_hash` 는 기록용(렌더한 지시문·본문 전부와 어댑터·세트·출력 스키마 이름의 sha256)이고, `cache_key` 는 같은 화
    입력이면 앞 작업의 제안을 다시 쓰는 열쇠다(정본 상태에서 오는 힌트는 뺀다). 어댑터 칸에는 CHECK 를 두지 않는다 — 어댑터는
    코드 표에서 늘어난다. 캐시로 가져온 제안의 원래 작업(`reused_from_job_id`)은 FK 가 없다.

    파이썬 None 은 JSON `null` 이 아니라 SQL NULL 로 쓴다 — `proposal` 이 JSON null 이면 "제안 없음" 판정(`IS NULL`)과 CHECK 가
    그 행을 제안이 있는 것으로 본다."""

    __tablename__ = "novel_bible_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    commit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_bible_commits.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[SlotId] = mapped_column(Text, nullable=False)
    status: Mapped[JobStatus] = mapped_column(Text, nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    # 재시도 대기 — 이 시각 전에는 고르지 않는다.
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    cache_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    adapter_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    reused_from_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    llm_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    failure_code: Mapped[JobFailure | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"slot IN ({_sql_in_list(SlotId)})", name="ck_novel_bible_jobs_slot"),
        CheckConstraint(f"status IN ({_sql_in_list(JobStatus)})", name="ck_novel_bible_jobs_status"),
        CheckConstraint("attempts >= 0", name="ck_novel_bible_jobs_attempts"),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({_sql_in_list(JobFailure)})", name="ck_novel_bible_jobs_failure"
        ),
        CheckConstraint(
            "(status = 'succeeded') = (proposal IS NOT NULL)", name="ck_novel_bible_jobs_proposal_iff_succeeded"
        ),
        # 확정 하나에 슬롯마다 작업 하나. 이 인덱스가 확정 DELETE 때 FK 검사도 겸한다.
        Index("ux_novel_bible_jobs_commit_slot", "commit_id", "slot", unique=True),
        Index("ix_novel_bible_jobs_queued", "available_at", "created_at", postgresql_where=text("status = 'queued'")),
        Index("ix_novel_bible_jobs_running", "claimed_at", postgresql_where=text("status = 'running'")),
        Index(
            "ix_novel_bible_jobs_cache", "novel_id", "slot", "cache_key", postgresql_where=text("status = 'succeeded'")
        ),
    )


class NovelBibleRevision(Base):
    """정본 기억 리비전 하나 = 커밋된 확정 하나. `id` 는 전역 고유이고 항목·근거·만료는 번호가 아니라 이 id 로 리비전을 가리킨다
    — 다른 가지가 같은 번호를 써도 항목이 섞이지 않는다. `revision_no` 는 `(novel_id, branch)` 안에서만 뜻이 있고, 그 유니크가
    커밋의 머리 비교(같은 머리에서 출발한 두 커밋 중 하나만 다음 번호를 얻는다)의 마지막 방어선이다.

    지운 화의 리비전은 이력째 사라져 번호에 구멍이 날 수 있다 — 머리는 최대 번호라 구멍과 무관하다. 앞 리비전이 지워지면
    `parent_revision_id` 가 비워진다."""

    __tablename__ = "novel_bible_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    branch: Mapped[str] = mapped_column(Text, nullable=False, server_default="canon")
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_bible_revisions.id", ondelete="SET NULL"), nullable=True
    )
    commit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_bible_commits.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("revision_no >= 1", name="ck_novel_bible_revisions_revision_no"),
        CheckConstraint("char_length(branch) BETWEEN 1 AND 64", name="ck_novel_bible_revisions_branch"),
        Index("ux_novel_bible_revisions_novel_branch_no", "novel_id", "branch", "revision_no", unique=True),
        Index("ux_novel_bible_revisions_commit_id", "commit_id", unique=True),
        Index("ix_novel_bible_revisions_parent", "parent_revision_id"),
    )


class NovelBibleEntity(Base):
    """소설 안의 인물·사물·능력 하나. 항목은 이름이 아니라 이 id 로 개체를 가리킨다.

    `novel_character_id` 는 처음 이을 때의 인물 카드 id 이고 FK 가 없으며 고치지 않는다 — 카드 합치기·삭제(사용자 행 잠금
    아래에서 도는 사용자 경로)가 정본 기억 행을 고치거나 잠그지 않게 하려는 것이다. 카드가 합쳐져 그 id 가 사라지면 읽는 쪽이
    개체의 이름·별칭으로 지금 카드를 다시 찾는다(합치기는 흡수된 이름을 남는 카드의 별칭으로 옮긴다). `(novel_id, kind,
    name_norm)` 유니크 덕에 동시에 잇는 두 확정이 같은 이름을 만들어도 개체 하나로 모인다."""

    __tablename__ = "novel_bible_entities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[EntityKind] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_norm: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    novel_character_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_sql_in_list(EntityKind)})", name="ck_novel_bible_entities_kind"),
        CheckConstraint("char_length(name_norm) BETWEEN 1 AND 200", name="ck_novel_bible_entities_name"),
        Index("ux_novel_bible_entities_novel_kind_name", "novel_id", "kind", "name_norm", unique=True),
    )


class NovelBibleEvidence(Base):
    """항목 하나의 근거 하나 — 원고 블록, 채팅 기억, 원문 채팅(쓰는 코드가 아직 없다), 원작 정본 중 하나를 가리킨다. 위치
    (블록 글 또는 원작 글 안의 구간)와 그 구간 글의 sha256 만 두고 인용 글 자체는 저장하지 않는다.

    `item_id` 는 `item_table` 이 정하는 여러 표를 가리키므로 FK 가 없다 — 항목과 같은 리비전에 매달려 함께 지워진다. 원본
    참조(화·개정·블록·방·채팅 기억·원작 버전·키워드 노트)도 FK 가 없어 원본이 사라져도 근거는 남는다."""

    __tablename__ = "novel_bible_evidence"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    created_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_bible_revisions.id", ondelete="CASCADE"), nullable=False
    )
    item_table: Mapped[ItemTable] = mapped_column(Text, nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    origin: Mapped[EvidenceOrigin] = mapped_column(Text, nullable=False)
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    chapter_revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    block_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    chat_room_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    chat_memory_fact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    chat_fact_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    content_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    source_field: Mapped[SourceField | None] = mapped_column(Text, nullable=True)
    keyword_note_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    # 출처마다 그 출처를 다시 찾는 데 필요한 칸이 모두 있어야 한다. 비교만 쓰면 빈 칸에서 식이 NULL 이 되어 통과하므로
    # `IS NOT NULL` 을 건다.
    __table_args__ = (
        CheckConstraint(f"item_table IN ({_sql_in_list(ItemTable)})", name="ck_novel_bible_evidence_item_table"),
        CheckConstraint(f"origin IN ({_sql_in_list(EvidenceOrigin)})", name="ck_novel_bible_evidence_origin"),
        CheckConstraint(
            "origin <> 'manuscript_block' OR (chapter_id IS NOT NULL AND chapter_revision_id IS NOT NULL"
            " AND block_id IS NOT NULL AND char_start IS NOT NULL AND char_end IS NOT NULL"
            " AND quote_sha256 IS NOT NULL)",
            name="ck_novel_bible_evidence_manuscript",
        ),
        CheckConstraint(
            "origin <> 'chat_memory' OR (chat_room_id IS NOT NULL AND chat_memory_fact_id IS NOT NULL"
            " AND chat_fact_key IS NOT NULL)",
            name="ck_novel_bible_evidence_chat_memory",
        ),
        CheckConstraint(
            "origin <> 'chat_message' OR chat_message_id IS NOT NULL", name="ck_novel_bible_evidence_chat_message"
        ),
        CheckConstraint(
            "origin <> 'source_canon' OR (content_version_id IS NOT NULL AND source_field IS NOT NULL"
            " AND char_start IS NOT NULL AND char_end IS NOT NULL AND quote_sha256 IS NOT NULL)",
            name="ck_novel_bible_evidence_source",
        ),
        CheckConstraint(
            f"source_field IS NULL OR source_field IN ({_sql_in_list(SourceField)})",
            name="ck_novel_bible_evidence_source_field",
        ),
        CheckConstraint(
            "source_field IS DISTINCT FROM 'keyword_note' OR keyword_note_id IS NOT NULL",
            name="ck_novel_bible_evidence_keyword_note",
        ),
        CheckConstraint(
            "char_start IS NULL OR (char_start >= 0 AND char_end > char_start)", name="ck_novel_bible_evidence_span"
        ),
        Index("ix_novel_bible_evidence_item", "item_table", "item_id"),
        Index("ix_novel_bible_evidence_created_revision", "created_revision_id"),
        Index(
            "ix_novel_bible_evidence_novel_chapter",
            "novel_id",
            "chapter_id",
            postgresql_where=text("origin = 'manuscript_block'"),
        ),
    )


class NovelBibleExpiration(Base):
    """리비전이 항목 하나를 현재에서 뺀다는 기록(덧붙이기만 한다). 화를 다시 확정하면 새 리비전이 그 화의 현재 항목 전부에
    `chapter_replaced` 를 남기고, 항목 행은 고치지 않는다. `edited` 는 직접 편집을 위해 자리만 잡아 둔 값이다.

    🔴 `(revision_id, item_table, item_id)` 복합 PK 는 `alembic check` 가 비교하지 않는다 — 검증은 `IntegrityError` 행위
    테스트뿐이다."""

    __tablename__ = "novel_bible_expirations"

    revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_bible_revisions.id", ondelete="CASCADE"), primary_key=True
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    item_table: Mapped[ItemTable] = mapped_column(Text, primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    reason: Mapped[ExpirationReason] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(f"item_table IN ({_sql_in_list(ItemTable)})", name="ck_novel_bible_expirations_item_table"),
        CheckConstraint(f"reason IN ({_sql_in_list(ExpirationReason)})", name="ck_novel_bible_expirations_reason"),
        Index("ix_novel_bible_expirations_item", "item_table", "item_id"),
    )


class NovelBibleFinding(Base):
    """확정 하나의 검사 결과 하나 — 차단(`block`)이면 확정이 `blocked` 로 끝나고, 경고는 커밋을 막지 않는다. `payload` 에는
    항목 참조·위치·근거 위치만 두고 인용 글은 넣지 않는다."""

    __tablename__ = "novel_bible_findings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    commit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_bible_commits.id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[FindingSeverity] = mapped_column(Text, nullable=False)
    rule: Mapped[FindingRule] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(f"severity IN ({_sql_in_list(FindingSeverity)})", name="ck_novel_bible_findings_severity"),
        CheckConstraint(f"rule IN ({_sql_in_list(FindingRule)})", name="ck_novel_bible_findings_rule"),
        Index("ix_novel_bible_findings_commit", "commit_id"),
    )


class NovelBibleAdaptationCandidate(Base):
    """원작이나 플레이와 다른 소설 사실 하나(각색 후보). `accepted`·`rejected` 는 자리만 잡아 둔 값이다.

    `fact_key` 는 소설 사실의 안정 키이고, `fact_id` 는 함께 커밋된 사실 행이다. `fact_id` 에 FK 를 두지 않는다 — 코어 표가
    슬롯 표에 묶이지 않게 하려는 것이고, 같은 리비전·화의 cascade 로 사실 행과 함께 지워진다."""

    __tablename__ = "novel_bible_adaptation_candidates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    created_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_bible_revisions.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_chapters.id", ondelete="CASCADE"), nullable=False
    )
    fact_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    fact_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    origin: Mapped[AdaptationOrigin] = mapped_column(Text, nullable=False)
    status: Mapped[AdaptationStatus] = mapped_column(Text, nullable=False, server_default="open")

    __table_args__ = (
        CheckConstraint(
            f"origin IN ({_sql_in_list(AdaptationOrigin)})", name="ck_novel_bible_adaptation_candidates_origin"
        ),
        CheckConstraint(
            f"status IN ({_sql_in_list(AdaptationStatus)})", name="ck_novel_bible_adaptation_candidates_status"
        ),
        Index("ix_novel_bible_adaptation_candidates_novel_key", "novel_id", "fact_key"),
        Index("ix_novel_bible_adaptation_candidates_created_revision", "created_revision_id"),
        Index("ix_novel_bible_adaptation_candidates_chapter", "chapter_id"),
    )


class NovelBibleItem:
    """항목 표(사건·회상 관계·사실·지식)의 공통 칸. 항목은 그것을 낸 확정의 화(`chapter_id`)와 커밋된 리비전
    (`created_revision_id`)에 매달려 둘 중 하나가 지워지면 함께 지워진다. `status` 는 `confirmed` 만 쓰고 나머지 값은 자리만
    잡아 두었다. 앞 항목을 대체한 항목은 표마다 `supersedes_id`(같은 표, 앞 행이 지워지면 비워진다)로 그 행을 가리킨다.

    표마다 `item_table_args` 로 상태 CHECK 와 공통 인덱스를 붙인다. 공통 칸은 `sort_order` 로 표의 앞자리에 둔다."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4, sort_order=-2)
    novel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, sort_order=-2
    )
    created_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_bible_revisions.id", ondelete="CASCADE"), nullable=False, sort_order=-2
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_chapters.id", ondelete="CASCADE"), nullable=False, sort_order=-2
    )
    status: Mapped[ItemStatus] = mapped_column(Text, nullable=False, server_default="confirmed", sort_order=-2)


def item_table_args(table: str) -> tuple[CheckConstraint | Index, ...]:
    """항목 표 `table` 의 상태 CHECK 와 공통 인덱스 — 소설·화 조회, 리비전 DELETE 때 FK 검사, 대체 사슬 DELETE 때 FK 검사."""
    return (
        CheckConstraint(f"status IN ({_sql_in_list(ItemStatus)})", name=f"ck_{table}_status"),
        Index(f"ix_{table}_novel_chapter", "novel_id", "chapter_id"),
        Index(f"ix_{table}_created_revision", "created_revision_id"),
        Index(f"ix_{table}_supersedes", "supersedes_id"),
    )
