"""여러 문단 수정 작업이 다른 쓰기와 실제로 겹칠 때(독립 커넥션) — 같은 소설의 두 요청, 실행 저장과 만료 환불.

같은 커넥션의 테스트로는 두 요청이 순서대로 돌아 경쟁이 드러나지 않는다. 상대 트랜잭션이 잠금을 쥔 채 커밋하지 않은 상태에서 함수를
띄우고, 그 함수가 정말 막혀 있는 것(`_assert_blocked`)을 먼저 확인한 뒤 상대를 커밋한다."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.db.models import Content, User
from api.db.models.clover import (
    CloverLedger,
    CloverLot,
    CloverSpendAllocation,
    CloverSpendRefund,
    CloverSpendUsage,
)
from api.db.models.novel import Novel, NovelChapterRevision, NovelJob
from api.novelize import billing, runner
from api.novelize.block_edits import BlockEdit, BlockEditPatch, request_targets
from api.novelize.deletion import delete_novels
from api.novelize.text import split_paragraphs
from factories import _assert_blocked, _make_draft_content, _make_novel_tree, _make_user_with_clover_lot

_MARKER_DOMAIN = "novelize-block-edit-races.test"


@pytest_asyncio.fixture
async def independent_factory(db_engine: AsyncEngine) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """커밋되는 독립 커넥션 세션 팩토리. 여기서 쓴 행은 롤백되지 않으므로 이 표지 도메인의 사용자와 그 아래 행을 끝에서 직접
    지운다(`test_novelize_billing.py` 의 같은 이름 픽스처와 같은 순서)."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory
    async with factory() as cleanup:
        user_ids = (await cleanup.scalars(select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if user_ids:
            novel_ids = (await cleanup.scalars(select(Novel.id).where(Novel.user_id.in_(user_ids)))).all()
            await delete_novels(cleanup, novel_ids, freed_storage_keys=[])
            spend_ledger_ids = select(CloverLedger.id).where(CloverLedger.user_id.in_(user_ids))
            allocation_ids = select(CloverSpendAllocation.id).where(
                CloverSpendAllocation.spend_ledger_id.in_(spend_ledger_ids)
            )
            await cleanup.execute(delete(CloverSpendRefund).where(CloverSpendRefund.allocation_id.in_(allocation_ids)))
            await cleanup.execute(delete(CloverSpendUsage).where(CloverSpendUsage.spend_ledger_id.in_(spend_ledger_ids)))
            await cleanup.execute(
                delete(CloverSpendAllocation).where(CloverSpendAllocation.spend_ledger_id.in_(spend_ledger_ids))
            )
            await cleanup.execute(delete(CloverLedger).where(CloverLedger.user_id.in_(user_ids)))
            await cleanup.execute(delete(CloverLot).where(CloverLot.user_id.in_(user_ids)))
            await cleanup.execute(delete(Content).where(Content.creator_user_id.in_(user_ids)))
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


async def _seed(factory: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID, NovelChapterRevision]:
    """잔액 100 인 작가, 화 하나짜리 소설(진행 중 작업 없음). 작가 id·소설 id·지금 개정을 돌려준다."""
    async with factory() as s:
        owner = await _make_user_with_clover_lot(s, clover_balance=100, email=f"be-{uuid.uuid4()}@{_MARKER_DOMAIN}")
        tree = await _make_novel_tree(s, owner.id)
        await s.delete(tree.active_job)
        # 차감이 사용처에 원작 소유자를 적으므로 원작 행이 있어야 한다.
        tree.novel.content_id = (await _make_draft_content(s, creator_user_id=owner.id)).id
        await s.commit()
        return owner.id, tree.novel.id, tree.reverting_revision


def _patch_job(novel_id: uuid.UUID, user_id: uuid.UUID, revision: NovelChapterRevision) -> NovelJob:
    targets = request_targets(revision.block_ids[:1], revision.block_ids, split_paragraphs(revision.body))
    return NovelJob(
        novel_id=novel_id,
        user_id=user_id,
        kind="ai_edit",
        chapter_id=revision.chapter_id,
        base_revision_id=revision.id,
        instruction="더 쓸쓸하게",
        block_edit=BlockEdit(targets=targets, scene_id=None).to_json(),
    )


async def _ledger(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> list[tuple[str, int]]:
    async with factory() as s:
        rows = await s.execute(
            select(CloverLedger.kind, CloverLedger.amount)
            .where(CloverLedger.user_id == user_id)
            .order_by(CloverLedger.amount, CloverLedger.kind)
        )
        return [(kind, amount) for kind, amount in rows.all()]


async def test_two_concurrent_block_edit_requests_for_one_novel_charge_once(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """같은 소설에 여러 문단 수정 두 요청이 겹치면 뒤 요청은 사용자 행에서 기다렸다가 앞 요청이 커밋한 진행 중 작업을 보고 409 이고
    차감하지 않는다. 깨지는 시나리오: 두 탭이 동시에 맡겨 두 번 차감되거나, 부분 유일 인덱스 위반이 500 으로 새어 나간다."""
    user_id, novel_id, revision = await _seed(independent_factory)
    first = independent_factory()
    try:
        # 앞 요청이 하는 일을 그대로: 사용자 잠금 → 진행 중 패치 작업 INSERT, 아직 커밋 전.
        await first.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
        ahead = _patch_job(novel_id, user_id, revision)
        ahead.status = "queued"
        ahead.charged_amount = 30
        first.add(ahead)
        await first.flush()

        async def second_request() -> object:
            async with independent_factory() as s:
                try:
                    return await billing.create_charged_job(
                        s, job=_patch_job(novel_id, user_id, revision), expected_cost=30, now=datetime.now(UTC)
                    )
                except HTTPException as exc:
                    return exc

        task = asyncio.ensure_future(second_request())
        await _assert_blocked(task)
        await first.commit()
        result = await task
    finally:
        await first.close()

    assert isinstance(result, HTTPException)
    detail: object = result.detail
    assert (result.status_code, detail) == (409, {"code": "NOVEL_JOB_IN_PROGRESS"})
    assert await _ledger(independent_factory, user_id) == []


async def test_a_save_racing_an_expiry_refund_loses_and_the_refund_happens_once(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """만료 정리의 환불이 작업 행을 실패로 바꾼 채 커밋 전이면 실행의 저장은 그 행에서 기다리고, 커밋 뒤에는 전이(실행 중 → 성공)가
    행을 받지 못해 패치를 쓰지 않는다. 환불은 한 번이다. 깨지는 시나리오: 환불된 작업에 패치가 남아 무료 수정안이 되거나, 성공과
    환불이 둘 다 일어난다."""
    user_id, novel_id, revision = await _seed(independent_factory)
    async with independent_factory() as s:
        job = await billing.create_charged_job(
            s, job=_patch_job(novel_id, user_id, revision), expected_cost=30, now=datetime.now(UTC)
        )
        await billing.transition_job(s, job_id=job.id, expected=("queued",), values={"status": "running"})
        await s.commit()
    targets = BlockEdit.model_validate(job.block_edit).targets
    patch = BlockEditPatch(
        id="p", block_id=targets[0].block_id, base_hash=targets[0].base_hash, paragraphs=["고친 글."], state="pending"
    )

    refund = independent_factory()
    try:
        assert await billing.refund_job(refund, job_id=job.id, failure_code="expired") == 30
        task = asyncio.ensure_future(runner._save_block_edit(independent_factory, job.id, [patch], []))
        await _assert_blocked(task)
        await refund.commit()
        await task
    finally:
        await refund.close()

    async with independent_factory() as s:
        stored = await s.get_one(NovelJob, job.id)
        assert (stored.status, stored.failure_code) == ("failed", "expired")
        assert stored.block_edit is not None and stored.block_edit["patches"] == []
    assert await _ledger(independent_factory, user_id) == [("novelize_spend", -30), ("novelize_refund", 30)]
