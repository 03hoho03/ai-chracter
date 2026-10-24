"""여러 문단 수정 작업이 다른 쓰기와 실제로 겹칠 때(독립 커넥션) — 같은 소설의 두 요청, 실행 저장과 만료 환불, 같은 블록을 고치는
두 작업의 동시 적용.

같은 커넥션의 테스트로는 두 요청이 순서대로 돌아 경쟁이 드러나지 않는다. 상대 트랜잭션이 잠금을 쥔 채 커밋하지 않은 상태에서 함수를
띄우고, 그 함수가 정말 막혀 있는 것(`_assert_blocked`)을 먼저 확인한 뒤 상대를 커밋한다."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

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
from api.db.models.novel import Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.novelize import billing, runner
from api.llm.client import LLMCallContext, LLMClient, T
from api.novelize.block_edit_router import apply_novel_block_edit, recheck_novel_block_edit_bundle
from api.novelize.block_edits import BlockEdit, BlockEditPatch, normalized_result, request_targets
from api.novelize.blocks import build_revision
from api.novelize.deletion import delete_novels
from api.novelize.schemas import NovelPatchUnitRequest
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
            await cleanup.execute(
                delete(CloverSpendUsage).where(CloverSpendUsage.spend_ledger_id.in_(spend_ledger_ids))
            )
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
        assert [target["baseHash"] for target in stored.block_edit["targets"]] == [""]
    assert await _ledger(independent_factory, user_id) == [("novelize_spend", -30), ("novelize_refund", 30)]


async def test_two_jobs_applying_patches_to_the_same_block_at_once_never_overwrite(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """같은 블록에 수정안을 낸 두 작업을 동시에 적용하면 둘 다 장 행에서 줄을 서고, 먼저 잡은 쪽만 개정을 쌓으며 뒤 쪽은 바뀐 블록을
    보고 409 `NOVEL_PATCH_STALE` 이다 — 개정은 하나만 늘고 그 블록은 앞 작업의 글이다. 깨지는 시나리오: 두 적용이 같은 개정을 기준으로
    차례로 쌓여 뒤 것이 앞 것의 수정을 덮어쓴다."""
    user_id, novel_id, revision = await _seed(independent_factory)
    job_ids: list[uuid.UUID] = []
    async with independent_factory() as s:
        for text in ("앞 작업의 글.", "뒤 작업의 글."):
            job = _patch_job(novel_id, user_id, revision)
            edit = BlockEdit.model_validate(job.block_edit)
            patches, _, _ = normalized_result(edit.targets, [(1, [text])], [])
            job.block_edit = edit.model_copy(update={"patches": patches}).to_json()
            job.status = "succeeded"
            job.charged_amount = 30
            s.add(job)
            await s.flush()
            job_ids.append(job.id)
        await s.commit()

    async def apply(job_id: uuid.UUID) -> object:
        async with independent_factory() as s:
            novel = await s.get_one(Novel, novel_id)
            stored = await s.get_one(NovelJob, job_id)
            patch_id = BlockEdit.model_validate(stored.block_edit).patches[0].id
            await s.commit()
            try:
                return await apply_novel_block_edit(
                    job_id=job_id, payload=NovelPatchUnitRequest(patch_id=patch_id), novel=novel, db=s
                )
            except HTTPException as exc:
                return exc

    blocker = independent_factory()
    try:
        # 다른 개정 쓰기가 장 행을 쥔 채 커밋 전 — 두 적용이 모두 그 뒤에서 기다린다.
        await blocker.execute(
            select(NovelChapter.id).where(NovelChapter.id == revision.chapter_id).with_for_update(key_share=True)
        )
        tasks = [asyncio.ensure_future(apply(job_id)) for job_id in job_ids]
        for task in tasks:
            await _assert_blocked(task)
        await blocker.rollback()
        results = await asyncio.gather(*tasks)
    finally:
        await blocker.close()

    refused = [r for r in results if isinstance(r, HTTPException)]
    assert len(refused) == 1
    detail: object = refused[0].detail
    assert refused[0].status_code == 409
    assert isinstance(detail, dict) and detail["code"] == "NOVEL_PATCH_STALE"
    async with independent_factory() as s:
        revisions = (
            await s.scalars(
                select(NovelChapterRevision)
                .where(NovelChapterRevision.chapter_id == revision.chapter_id)
                .order_by(NovelChapterRevision.revision_no)
            )
        ).all()
    assert [r.revision_no for r in revisions] == [1, 2, 3]
    winner = 0 if not isinstance(results[0], HTTPException) else 1
    assert split_paragraphs(revisions[-1].body) == [("앞 작업의 글.", "뒤 작업의 글.")[winner]]


class _SeparableLLM(LLMClient):
    """재검사에 "따로 적용해도 된다"를 돌려준다. `during` 은 모델을 부르는 순간 실행할 일이다."""

    def __init__(self, during: Callable[[], Awaitable[None]]) -> None:
        self.during = during

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise AssertionError("재검사는 스트리밍 호출을 쓰지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("재검사는 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        await self.during()
        return response_schema.model_validate({"separable": True, "reason": "같은 사실이 남아 있다."})


async def test_a_recheck_verdict_waits_for_a_concurrent_edit_and_is_discarded_by_it(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """재검사가 판정을 쓰려는 순간 다른 탭의 직접 수정이 장 행을 쥔 채 커밋 전이면 재검사는 그 장 행에서 기다리고, 커밋 뒤 새 개정을
    보고 409 `NOVEL_REVISION_CONFLICT` 로 판정을 버린다 — 묶음은 그대로다. 깨지는 시나리오: 확인과 커밋 사이에 들어온 수정을 못 보고 옛
    글에 대한 판정으로 묶음을 나눈다."""
    user_id, novel_id, seeded = await _seed(independent_factory)
    async with independent_factory() as s:
        # 문단 셋짜리 개정 → 첫째·둘째 묶음 수정안 → 사용자가 첫째를 고친 개정.
        base = build_revision(
            body="가 문단.\n\n나 문단.\n\n다 문단.",
            source="manual_edit",
            block_ids=[uuid.uuid4() for _ in range(3)],
            chapter_id=seeded.chapter_id,
            revision_no=3,
        )
        s.add(base)
        await s.flush()
        targets = request_targets(base.block_ids[:2], base.block_ids, split_paragraphs(base.body))
        patches, bundles, _ = normalized_result(targets, [(1, ["고친 가."]), (2, ["고친 나."])], [([1, 2], "기댄다")])
        job = NovelJob(
            novel_id=novel_id,
            user_id=user_id,
            kind="ai_edit",
            status="succeeded",
            chapter_id=seeded.chapter_id,
            base_revision_id=base.id,
            instruction="더 쓸쓸하게",
            charged_amount=30,
            block_edit=BlockEdit(targets=targets, scene_id=None, patches=patches, bundles=bundles).to_json(),
        )
        s.add(job)
        s.add(
            build_revision(
                body="사용자가 고친 가.\n\n나 문단.\n\n다 문단.",
                source="manual_edit",
                block_ids=base.block_ids,
                chapter_id=seeded.chapter_id,
                revision_no=4,
            )
        )
        await s.commit()
    (bundle,) = bundles

    blocker = independent_factory()
    ready = asyncio.Event()

    async def other_tab_edits() -> None:
        # 다른 탭의 직접 수정이 장 행을 잡고 새 개정을 넣은 채 아직 커밋 전.
        await blocker.execute(
            select(NovelChapter.id).where(NovelChapter.id == seeded.chapter_id).with_for_update(key_share=True)
        )
        blocker.add(
            build_revision(
                body="사용자가 또 고친 가.\n\n나 문단.\n\n다 문단.",
                source="manual_edit",
                block_ids=base.block_ids,
                chapter_id=seeded.chapter_id,
                revision_no=5,
            )
        )
        await blocker.flush()
        ready.set()

    async def recheck() -> object:
        async with independent_factory() as s:
            novel = await s.get_one(Novel, novel_id)
            try:
                return await recheck_novel_block_edit_bundle(
                    job_id=job.id, bundle_id=bundle.id, novel=novel, db=s, llm_client=_SeparableLLM(other_tab_edits)
                )
            except HTTPException as exc:
                return exc

    try:
        task = asyncio.ensure_future(recheck())
        await ready.wait()
        await _assert_blocked(task)
        await blocker.commit()
        result = await task
    finally:
        await blocker.close()

    assert isinstance(result, HTTPException)
    detail: object = result.detail
    assert (result.status_code, detail) == (409, {"code": "NOVEL_REVISION_CONFLICT"})
    async with independent_factory() as s:
        stored = await s.get_one(NovelJob, job.id)
        assert BlockEdit.model_validate(stored.block_edit).bundles == [bundle]
