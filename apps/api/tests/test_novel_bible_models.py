"""정본 기억 표의 CHECK 제약, 복합 PK, 유니크·부분 유니크 인덱스.

`alembic check` 는 CHECK 제약과 복합 PK 를 비교하지 않고 부분 인덱스의 조건식도 비교하지 않는다 — 이 불변식들은 여기
행위 테스트에서만 검증된다. 지우지 말 것. 경우마다 경계 안쪽 값이 들어가는 것과 바깥 값이 그 제약 이름으로 거부되는 것을
함께 본다 — 거부만 보면 모든 값을 막는 제약도 통과하고, 수락만 보면 제약이 없어도 통과한다."""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.base import Base
from api.db.models import (
    NovelBibleAdaptationCandidate,
    NovelBibleCommit,
    NovelBibleEntity,
    NovelBibleEvent,
    NovelBibleEventRelation,
    NovelBibleEvidence,
    NovelBibleExpiration,
    NovelBibleFact,
    NovelBibleFinding,
    NovelBibleJob,
    NovelBibleKnowledge,
    NovelBibleRevision,
)
from factories import BibleRows, NovelTree, _make_novel_tree, _make_user, _plant_bible_rows


@dataclass(frozen=True)
class _Ctx:
    tree: NovelTree
    rows: BibleRows
    # 작업·리비전이 아직 없는 커밋된 확정 — 작업·리비전 행을 새로 넣는 경우가 심어 둔 행과 유니크로 겹치지 않게 쓴다.
    spare_commit_id: uuid.UUID


async def _ctx(db_session: AsyncSession) -> _Ctx:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    tree = await _make_novel_tree(db_session, user.id)
    rows = await _plant_bible_rows(
        db_session, novel_id=tree.novel.id, chapter_id=tree.chapter.id, chapter_revision_id=tree.first_revision.id
    )
    spare = NovelBibleCommit(**_commit_values(tree))
    db_session.add(spare)
    await db_session.flush()
    return _Ctx(tree, rows, spare.id)


def _commit_values(tree: NovelTree, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "novel_id": tree.novel.id,
        "kind": "chapter_confirm",
        "chapter_id": tree.chapter.id,
        "chapter_revision_id": tree.first_revision.id,
        "content_hash": "0" * 64,
        "block_ids_hash": "0" * 64,
        "status": "committed",
        "actor_kind": "system",
    }
    values.update(overrides)
    return values


def _item_values(ctx: _Ctx) -> dict[str, Any]:
    return {
        "novel_id": ctx.tree.novel.id,
        "created_revision_id": ctx.rows.revision_id,
        "chapter_id": ctx.tree.chapter.id,
    }


def _base_values(model: type[Base], ctx: _Ctx) -> dict[str, Any]:
    """`model` 에 들어가는 행 하나. 부를 때마다 FK 없는 uuid 칸을 새로 뽑아, 같은 경우의 두 행이 PK·유니크로 겹치지 않는다."""
    novel_id = ctx.tree.novel.id
    if model is NovelBibleCommit:
        return _commit_values(ctx.tree)
    if model is NovelBibleJob:
        return {"novel_id": novel_id, "commit_id": ctx.spare_commit_id, "slot": "events", "status": "queued"}
    if model is NovelBibleRevision:
        return {"novel_id": novel_id, "revision_no": 2, "commit_id": ctx.spare_commit_id}
    if model is NovelBibleEntity:
        return {"novel_id": novel_id, "kind": "character", "name": "다른 인물", "name_norm": "다른 인물"}
    if model is NovelBibleEvidence:
        return {
            "novel_id": novel_id,
            "created_revision_id": ctx.rows.revision_id,
            "item_table": "fact",
            "item_id": uuid.uuid4(),
            "origin": "chat_message",
            "chat_message_id": uuid.uuid4(),
        }
    if model is NovelBibleExpiration:
        return {
            "revision_id": ctx.rows.revision_id,
            "novel_id": novel_id,
            "item_table": "event",
            "item_id": uuid.uuid4(),
            "reason": "chapter_replaced",
        }
    if model is NovelBibleFinding:
        return {
            "novel_id": novel_id,
            "commit_id": ctx.rows.commit_id,
            "severity": "warning",
            "rule": "order_undetermined",
            "payload": {},
        }
    if model is NovelBibleAdaptationCandidate:
        return {**_item_values(ctx), "fact_key": uuid.uuid4(), "fact_id": uuid.uuid4(), "origin": "play"}
    if model is NovelBibleEvent:
        return {
            **_item_values(ctx),
            "ordinal": 1,
            "actuality": "present",
            "summary": "합성 사건",
            "anchor_block_ids": [uuid.uuid4()],
        }
    if model is NovelBibleEventRelation:
        return {
            **_item_values(ctx),
            "from_event_id": ctx.rows.event_id,
            "relation": "before",
            "to_anchor_block_id": uuid.uuid4(),
            "to_chapter_id": ctx.tree.chapter.id,
        }
    if model is NovelBibleFact:
        return {
            **_item_values(ctx),
            "fact_key": uuid.uuid4(),
            "subject_entity_id": ctx.rows.entity_id,
            "kind": "life",
            "predicate_norm": "life",
            "value": "살아 있음",
            "value_norm": "alive",
            "holds": True,
            "immutable": False,
            "onset": False,
            "scope": "from_here",
        }
    assert model is NovelBibleKnowledge
    return {
        **_item_values(ctx),
        "knower_entity_id": ctx.rows.entity_id,
        "kind": "knows",
        "fact_key": uuid.uuid4(),
        "proposition": {},
    }


# 경우 목록의 값 자리에 두면 심어 둔 개체 id 로 바뀐다(개체를 가리키는 칸은 FK 라 아무 uuid 나 쓸 수 없다).
_ENTITY = "<entity>"


async def _insert(db_session: AsyncSession, model: type[Base], values: dict[str, Any]) -> None:
    async with db_session.begin_nested():
        await db_session.execute(sa.insert(model).values(**values))


def _resolved(ctx: _Ctx, overrides: dict[str, Any]) -> dict[str, Any]:
    return {key: ctx.rows.entity_id if value == _ENTITY else value for key, value in overrides.items()}


def _case(model: type[Base], accepted: dict[str, Any], rejected: dict[str, Any], constraint: str, case_id: str) -> Any:
    return pytest.param(model, accepted, rejected, constraint, id=case_id)


_CHECK_CASES = [
    # 확정
    _case(
        NovelBibleCommit,
        {
            "kind": "direct_edit",
            "chapter_id": None,
            "chapter_revision_id": None,
            "content_hash": None,
            "block_ids_hash": None,
        },
        {
            "kind": "chapter_edit",
            "chapter_id": None,
            "chapter_revision_id": None,
            "content_hash": None,
            "block_ids_hash": None,
        },
        "ck_novel_bible_commits_kind",
        "commit-kind",
    ),
    _case(NovelBibleCommit, {"status": "stale"}, {"status": "done"}, "ck_novel_bible_commits_status", "commit-status"),
    _case(
        NovelBibleCommit,
        {"branch": "b" * 64},
        {"branch": "b" * 65},
        "ck_novel_bible_commits_branch",
        "commit-branch-long",
    ),
    _case(NovelBibleCommit, {"branch": "b"}, {"branch": ""}, "ck_novel_bible_commits_branch", "commit-branch-empty"),
    _case(
        NovelBibleCommit,
        {},
        {"chapter_revision_id": None},
        "ck_novel_bible_commits_chapter_ref",
        "commit-confirm-without-revision",
    ),
    _case(
        NovelBibleCommit,
        {
            "kind": "direct_edit",
            "chapter_id": None,
            "chapter_revision_id": None,
            "content_hash": None,
            "block_ids_hash": None,
        },
        {"kind": "direct_edit"},
        "ck_novel_bible_commits_chapter_ref",
        "commit-direct-edit-with-chapter",
    ),
    _case(
        NovelBibleCommit,
        {"actor_kind": "admin", "actor_id": uuid.uuid4()},
        {"actor_kind": "admin"},
        "ck_novel_bible_commits_actor",
        "commit-admin-without-id",
    ),
    _case(
        NovelBibleCommit,
        {"actor_kind": "user"},
        {"actor_kind": "robot"},
        "ck_novel_bible_commits_actor",
        "commit-actor-kind",
    ),
    _case(
        NovelBibleCommit,
        {"status": "failed", "failure_code": "stalled"},
        {"status": "failed", "failure_code": "network"},
        "ck_novel_bible_commits_failure",
        "commit-failure-code",
    ),
    _case(
        NovelBibleCommit,
        {"status": "failed", "failure_code": "internal"},
        {"status": "failed"},
        "ck_novel_bible_commits_failure_iff_failed",
        "commit-failed-without-code",
    ),
    _case(
        NovelBibleCommit,
        {"status": "committed"},
        {"status": "committed", "failure_code": "internal"},
        "ck_novel_bible_commits_failure_iff_failed",
        "commit-code-without-failure",
    ),
    _case(
        NovelBibleCommit,
        {"cas_losses": 0},
        {"cas_losses": -1},
        "ck_novel_bible_commits_cas_losses",
        "commit-cas-losses",
    ),
    _case(NovelBibleCommit, {"restarts": 0}, {"restarts": -1}, "ck_novel_bible_commits_restarts", "commit-restarts"),
    # 슬롯 작업
    _case(NovelBibleJob, {"slot": "source"}, {"slot": "plot"}, "ck_novel_bible_jobs_slot", "job-slot"),
    _case(NovelBibleJob, {"status": "running"}, {"status": "done"}, "ck_novel_bible_jobs_status", "job-status"),
    _case(NovelBibleJob, {"attempts": 0}, {"attempts": -1}, "ck_novel_bible_jobs_attempts", "job-attempts"),
    _case(
        NovelBibleJob,
        {"status": "failed", "failure_code": "input_too_large"},
        {"status": "failed", "failure_code": "network"},
        "ck_novel_bible_jobs_failure",
        "job-failure-code",
    ),
    _case(
        NovelBibleJob,
        {"status": "succeeded", "proposal": {}},
        {"status": "succeeded"},
        "ck_novel_bible_jobs_proposal_iff_succeeded",
        "job-succeeded-without-proposal",
    ),
    _case(
        NovelBibleJob,
        {"status": "queued", "proposal": None},
        {"status": "queued", "proposal": {}},
        "ck_novel_bible_jobs_proposal_iff_succeeded",
        "job-proposal-before-success",
    ),
    # 리비전
    _case(
        NovelBibleRevision,
        {"revision_no": 1, "branch": "other"},
        {"revision_no": 0},
        "ck_novel_bible_revisions_revision_no",
        "revision-no",
    ),
    _case(
        NovelBibleRevision, {"branch": "b" * 64}, {"branch": ""}, "ck_novel_bible_revisions_branch", "revision-branch"
    ),
    # 개체
    _case(NovelBibleEntity, {"kind": "ability"}, {"kind": "place"}, "ck_novel_bible_entities_kind", "entity-kind"),
    _case(
        NovelBibleEntity,
        {"name_norm": "n" * 200},
        {"name_norm": "n" * 201},
        "ck_novel_bible_entities_name",
        "entity-name-long",
    ),
    _case(NovelBibleEntity, {"name_norm": "n"}, {"name_norm": ""}, "ck_novel_bible_entities_name", "entity-name-empty"),
    # 근거
    _case(
        NovelBibleEvidence,
        {"item_table": "adaptation_candidate"},
        {"item_table": "chapter"},
        "ck_novel_bible_evidence_item_table",
        "evidence-item-table",
    ),
    _case(NovelBibleEvidence, {}, {"origin": "web"}, "ck_novel_bible_evidence_origin", "evidence-origin"),
    _case(
        NovelBibleEvidence,
        {
            "origin": "manuscript_block",
            "chat_message_id": None,
            "chapter_id": uuid.uuid4(),
            "chapter_revision_id": uuid.uuid4(),
            "block_id": uuid.uuid4(),
            "char_start": 0,
            "char_end": 1,
            "quote_sha256": "0" * 64,
        },
        {
            "origin": "manuscript_block",
            "chat_message_id": None,
            "chapter_id": uuid.uuid4(),
            "chapter_revision_id": uuid.uuid4(),
            "char_start": 0,
            "char_end": 1,
            "quote_sha256": "0" * 64,
        },
        "ck_novel_bible_evidence_manuscript",
        "evidence-manuscript-without-block",
    ),
    _case(
        NovelBibleEvidence,
        {
            "origin": "chat_memory",
            "chat_message_id": None,
            "chat_room_id": uuid.uuid4(),
            "chat_memory_fact_id": uuid.uuid4(),
            "chat_fact_key": "합성 키",
        },
        {
            "origin": "chat_memory",
            "chat_message_id": None,
            "chat_room_id": uuid.uuid4(),
            "chat_memory_fact_id": uuid.uuid4(),
        },
        "ck_novel_bible_evidence_chat_memory",
        "evidence-chat-memory-without-key",
    ),
    _case(
        NovelBibleEvidence,
        {},
        {"chat_message_id": None},
        "ck_novel_bible_evidence_chat_message",
        "evidence-chat-message-without-id",
    ),
    _case(
        NovelBibleEvidence,
        {
            "origin": "source_canon",
            "chat_message_id": None,
            "content_version_id": uuid.uuid4(),
            "source_field": "work_setting",
            "char_start": 0,
            "char_end": 1,
            "quote_sha256": "0" * 64,
        },
        {
            "origin": "source_canon",
            "chat_message_id": None,
            "content_version_id": uuid.uuid4(),
            "source_field": "work_setting",
            "char_start": 0,
            "char_end": 1,
        },
        "ck_novel_bible_evidence_source",
        "evidence-source-without-quote-hash",
    ),
    _case(
        NovelBibleEvidence,
        {"source_field": "work_setting"},
        {"source_field": "notes"},
        "ck_novel_bible_evidence_source_field",
        "evidence-source-field",
    ),
    _case(
        NovelBibleEvidence,
        {"source_field": "keyword_note", "keyword_note_id": uuid.uuid4()},
        {"source_field": "keyword_note"},
        "ck_novel_bible_evidence_keyword_note",
        "evidence-keyword-note-without-id",
    ),
    _case(
        NovelBibleEvidence,
        {"char_start": 0, "char_end": 1},
        {"char_start": 3, "char_end": 3},
        "ck_novel_bible_evidence_span",
        "evidence-empty-span",
    ),
    _case(
        NovelBibleEvidence,
        {"char_start": 3, "char_end": 4},
        {"char_start": -1, "char_end": 4},
        "ck_novel_bible_evidence_span",
        "evidence-negative-start",
    ),
    # 만료·검사 결과·각색 후보
    _case(
        NovelBibleExpiration,
        {"item_table": "knowledge"},
        {"item_table": "chapter"},
        "ck_novel_bible_expirations_item_table",
        "expiration-item-table",
    ),
    _case(
        NovelBibleExpiration,
        {"reason": "edited"},
        {"reason": "deleted"},
        "ck_novel_bible_expirations_reason",
        "expiration-reason",
    ),
    _case(
        NovelBibleFinding,
        {"severity": "block"},
        {"severity": "info"},
        "ck_novel_bible_findings_severity",
        "finding-severity",
    ),
    _case(
        NovelBibleFinding,
        {"rule": "exit_then_appearance"},
        {"rule": "plot_hole"},
        "ck_novel_bible_findings_rule",
        "finding-blocking-rule",
    ),
    _case(
        NovelBibleFinding,
        {"rule": "judge_failed"},
        {"rule": "plot_hole"},
        "ck_novel_bible_findings_rule",
        "finding-warning-rule",
    ),
    _case(
        NovelBibleAdaptationCandidate,
        {"origin": "source_canon"},
        {"origin": "chat"},
        "ck_novel_bible_adaptation_candidates_origin",
        "adaptation-origin",
    ),
    _case(
        NovelBibleAdaptationCandidate,
        {"status": "rejected"},
        {"status": "pending"},
        "ck_novel_bible_adaptation_candidates_status",
        "adaptation-status",
    ),
    # 항목 표 공통 상태 — `superseded` 는 상태 값이 아니다(대체는 만료 행과 새 행으로 나타낸다).
    _case(
        NovelBibleEvent, {"status": "planned"}, {"status": "superseded"}, "ck_novel_bible_events_status", "event-status"
    ),
    _case(
        NovelBibleEventRelation,
        {"status": "needs_alignment"},
        {"status": "superseded"},
        "ck_novel_bible_event_relations_status",
        "relation-status",
    ),
    _case(
        NovelBibleFact, {"status": "proposed"}, {"status": "superseded"}, "ck_novel_bible_facts_status", "fact-status"
    ),
    _case(
        NovelBibleKnowledge,
        {"status": "approved_for_revision"},
        {"status": "superseded"},
        "ck_novel_bible_knowledge_status",
        "knowledge-status",
    ),
    # 사건·회상 관계
    _case(NovelBibleEvent, {"ordinal": 1}, {"ordinal": 0}, "ck_novel_bible_events_ordinal", "event-ordinal"),
    _case(
        NovelBibleEvent,
        {"actuality": "dream_or_imagined"},
        {"actuality": "imagined"},
        "ck_novel_bible_events_actuality",
        "event-actuality",
    ),
    _case(NovelBibleEvent, {}, {"anchor_block_ids": []}, "ck_novel_bible_events_anchor", "event-without-anchor"),
    _case(
        NovelBibleEventRelation,
        {"relation": "overlap"},
        {"relation": "during"},
        "ck_novel_bible_event_relations_relation",
        "relation-kind",
    ),
    # 사실
    _case(
        NovelBibleFact,
        {"kind": "attribute", "predicate_norm": "키", "value_norm": "큼"},
        {"kind": "location", "predicate_norm": "곳", "value_norm": "집"},
        "ck_novel_bible_facts_kind",
        "fact-kind",
    ),
    _case(NovelBibleFact, {"scope": "scene"}, {"scope": "chapter"}, "ck_novel_bible_facts_scope", "fact-scope"),
    _case(
        NovelBibleFact,
        {"immutable": True, "kind": "attribute", "predicate_norm": "혈액형", "value_norm": "a", "scope": "work"},
        {"immutable": True, "kind": "attribute", "predicate_norm": "혈액형", "value_norm": "a", "scope": "from_here"},
        "ck_novel_bible_facts_immutable",
        "fact-immutable-outside-work-scope",
    ),
    _case(
        NovelBibleFact,
        {"immutable": True, "kind": "attribute", "predicate_norm": "혈액형", "value_norm": "a", "scope": "work"},
        {"immutable": True, "scope": "work"},
        "ck_novel_bible_facts_immutable",
        "fact-immutable-non-attribute",
    ),
    _case(
        NovelBibleFact,
        {"holds": False, "kind": "possession", "predicate_norm": "possession", "value_entity_id": _ENTITY},
        {"holds": False},
        "ck_novel_bible_facts_holds",
        "fact-life-not-holding",
    ),
    _case(
        NovelBibleFact,
        {"value_norm": "dead"},
        {"value_norm": "missing"},
        "ck_novel_bible_facts_life",
        "fact-life-value",
    ),
    _case(
        NovelBibleFact,
        {"kind": "presence", "predicate_norm": "presence", "value_norm": "gone_for_good"},
        {"kind": "presence", "predicate_norm": "presence", "value_norm": "alive"},
        "ck_novel_bible_facts_presence",
        "fact-presence-value",
    ),
    _case(
        NovelBibleFact,
        {"onset": True, "scope": "from_here"},
        {"onset": True, "scope": "work"},
        "ck_novel_bible_facts_onset",
        "fact-onset-in-work-scope",
    ),
    _case(
        NovelBibleFact,
        {"kind": "relation", "predicate_norm": "친구", "value_entity_id": _ENTITY},
        {"kind": "relation", "predicate_norm": "친구"},
        "ck_novel_bible_facts_value_entity",
        "fact-relation-without-entity",
    ),
    _case(
        NovelBibleFact,
        {"kind": "ability", "predicate_norm": "ability", "value_entity_id": _ENTITY},
        {"value_entity_id": _ENTITY},
        "ck_novel_bible_facts_value_entity",
        "fact-life-with-entity",
    ),
    # 지식
    _case(
        NovelBibleKnowledge,
        {"kind": "believes"},
        {"kind": "suspects"},
        "ck_novel_bible_knowledge_kind",
        "knowledge-kind",
    ),
]


@pytest.mark.parametrize(("model", "accepted", "rejected", "constraint"), _CHECK_CASES)
async def test_bible_check_constraints_admit_the_edge_and_reject_just_past_it(
    db_session: AsyncSession, model: type[Base], accepted: dict[str, Any], rejected: dict[str, Any], constraint: str
) -> None:
    ctx = await _ctx(db_session)

    await _insert(db_session, model, {**_base_values(model, ctx), **_resolved(ctx, accepted)})
    with pytest.raises(IntegrityError, match=constraint):
        await _insert(db_session, model, {**_base_values(model, ctx), **_resolved(ctx, rejected)})


async def test_a_chapter_has_at_most_one_in_flight_commit_per_branch(db_session: AsyncSession) -> None:
    """새 확정이 들어오면 앞 것을 낡음으로 돌린 뒤 넣는다 — 부분 유니크가 그 순서를 강제한다. 다른 가지와 끝난 확정은 막지
    않는다."""
    ctx = await _ctx(db_session)
    first = _commit_values(ctx.tree, id=uuid.uuid4(), status="pending")
    await _insert(db_session, NovelBibleCommit, first)
    await _insert(db_session, NovelBibleCommit, _commit_values(ctx.tree, status="checking", branch="other"))

    with pytest.raises(IntegrityError, match="ux_novel_bible_commits_in_flight"):
        await _insert(db_session, NovelBibleCommit, _commit_values(ctx.tree, status="extracting"))

    await db_session.execute(
        sa.update(NovelBibleCommit).where(NovelBibleCommit.id == first["id"]).values(status="stale")
    )
    await _insert(db_session, NovelBibleCommit, _commit_values(ctx.tree, status="extracting"))


async def test_a_commit_runs_each_slot_once(db_session: AsyncSession) -> None:
    ctx = await _ctx(db_session)
    job = {"novel_id": ctx.tree.novel.id, "commit_id": ctx.spare_commit_id, "status": "queued"}
    await _insert(db_session, NovelBibleJob, {**job, "slot": "events"})
    await _insert(db_session, NovelBibleJob, {**job, "slot": "facts"})

    with pytest.raises(IntegrityError, match="ux_novel_bible_jobs_commit_slot"):
        await _insert(db_session, NovelBibleJob, {**job, "slot": "events"})


async def test_revision_numbers_are_unique_per_novel_and_branch(db_session: AsyncSession) -> None:
    """리비전 번호 유니크가 머리 비교의 마지막 방어선이다 — 같은 머리에서 출발한 두 커밋 중 하나만 다음 번호를 얻는다."""
    ctx = await _ctx(db_session)
    revision = {"novel_id": ctx.tree.novel.id, "revision_no": 1, "commit_id": ctx.spare_commit_id}

    with pytest.raises(IntegrityError, match="ux_novel_bible_revisions_novel_branch_no"):
        await _insert(db_session, NovelBibleRevision, revision)

    await _insert(db_session, NovelBibleRevision, {**revision, "branch": "other"})


async def test_a_commit_makes_at_most_one_revision(db_session: AsyncSession) -> None:
    ctx = await _ctx(db_session)
    revision = {"novel_id": ctx.tree.novel.id, "revision_no": 2}

    with pytest.raises(IntegrityError, match="ux_novel_bible_revisions_commit_id"):
        await _insert(db_session, NovelBibleRevision, {**revision, "commit_id": ctx.rows.commit_id})

    await _insert(db_session, NovelBibleRevision, {**revision, "commit_id": ctx.spare_commit_id})


async def test_entity_names_are_unique_per_novel_and_kind(db_session: AsyncSession) -> None:
    """동시에 연결하는 두 확정이 같은 이름을 만들어도 개체 하나로 모이는 근거다. 종류가 다르면 같은 이름이 둘 있어도 된다."""
    ctx = await _ctx(db_session)
    planted = await db_session.get_one(NovelBibleEntity, ctx.rows.entity_id)
    entity = {"novel_id": ctx.tree.novel.id, "name": planted.name, "name_norm": planted.name_norm}

    with pytest.raises(IntegrityError, match="ux_novel_bible_entities_novel_kind_name"):
        await _insert(db_session, NovelBibleEntity, {**entity, "kind": "character"})

    await _insert(db_session, NovelBibleEntity, {**entity, "kind": "object"})


async def test_an_item_expires_at_most_once_per_revision(db_session: AsyncSession) -> None:
    """만료 행의 복합 PK — 같은 리비전이 같은 항목을 두 번 만료하지 않는다. 표가 다르면 같은 id 라도 다른 항목이다."""
    ctx = await _ctx(db_session)
    expiration = {
        "revision_id": ctx.rows.revision_id,
        "novel_id": ctx.tree.novel.id,
        "item_id": ctx.rows.event_id,
        "reason": "chapter_replaced",
    }

    with pytest.raises(IntegrityError, match="novel_bible_expirations_pkey"):
        await _insert(db_session, NovelBibleExpiration, {**expiration, "item_table": "event"})

    await _insert(db_session, NovelBibleExpiration, {**expiration, "item_table": "fact"})
