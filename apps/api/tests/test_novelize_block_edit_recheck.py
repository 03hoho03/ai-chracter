"""묶음 재검사(`POST /novels/{id}/jobs/{jobId}/bundles/{bundleId}/recheck`) — 사용자가 묶음 원소의 블록을 고친 뒤 남은 수정안을 따로
적용해도 되는지 모델에 묻고(무료, 시간당 상한), 된다면 고친 원소를 묶음에서 뺀다. 모델은 가짜다."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, T
from api.novelize.block_edits import BlockEdit, normalized_result, request_targets
from api.novelize.text import split_paragraphs
from factories import (
    _add_chapter,
    _clear_llm_override,
    _novel_ledger,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_BODY = "첫 문단이다.\n\n둘째 문단이다.\n\n셋째 문단이다.\n\n넷째 문단이다."


class _RecheckLLM(LLMClient):
    """재검사 페이크. 구조화 호출에 `result` 를 돌려주거나 `error` 를 낸다. `during` 은 모델을 부르는 순간 실행할 일이다."""

    def __init__(
        self,
        result: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
        during: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.result = result if result is not None else {"separable": True, "reason": "고친 문단에 같은 사실이 있다."}
        self.error = error
        self.during = during
        self.calls: list[tuple[str, str, LLMCallContext, type]] = []

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
        self.calls.append((prompt, system_instruction, usage, response_schema))
        if self.during is not None:
            await self.during()
        if self.error is not None:
            raise self.error
        return response_schema.model_validate(self.result)


@pytest.fixture
def fake() -> Iterator[_RecheckLLM]:
    llm = _RecheckLLM()
    _override_llm_client(llm)
    yield llm
    _clear_llm_override()


@pytest.fixture(autouse=True)
def _switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_multi_block_edit_enabled", True)


async def _chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[uuid.UUID, uuid.UUID, NovelChapter]:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1], body=_BODY)
    return room.user_id, novel_id, chapter


async def _current(db: AsyncSession, chapter_id: uuid.UUID) -> NovelChapterRevision:
    revision = await db.scalar(
        sa.select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    assert revision is not None
    return revision


async def _bundle_job(
    db: AsyncSession, novel_id: uuid.UUID, chapter: NovelChapter, base: NovelChapterRevision, members: list[int]
) -> NovelJob:
    targets = request_targets([base.block_ids[i] for i in members], base.block_ids, split_paragraphs(base.body))
    patches, bundles, _ = normalized_result(
        targets,
        [(i + 1, [f"고친 {i + 1}."]) for i in members],
        [([i + 1 for i in members], "앞이 정한 사실을 뒤가 쓴다")],
    )
    job = NovelJob(
        novel_id=novel_id,
        user_id=(await db.get_one(Novel, novel_id)).user_id,
        kind="ai_edit",
        status="succeeded",
        chapter_id=chapter.id,
        base_revision_id=base.id,
        instruction="더 쓸쓸하게",
        charged_amount=20,
        block_edit=BlockEdit(targets=targets, scene_id=None, patches=patches, bundles=bundles).to_json(),
    )
    db.add(job)
    await db.commit()
    return job


async def _edit(db: AsyncSession, job_id: uuid.UUID) -> BlockEdit:
    job = await db.scalar(sa.select(NovelJob).where(NovelJob.id == job_id).execution_options(populate_existing=True))
    assert job is not None and job.block_edit is not None
    return BlockEdit.model_validate(job.block_edit)


async def _edit_directly(
    client: httpx.AsyncClient,
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    base: NovelChapterRevision,
    old: str,
    new: str,
) -> None:
    resp = await client.post(
        f"/novels/{novel_id}/chapters/{chapter_id}/revisions",
        json={"baseRevisionId": str(base.id), "body": base.body.replace(old, new)},
    )
    assert resp.status_code == 201, resp.text


def _url(novel_id: uuid.UUID, job_id: uuid.UUID, bundle_id: str) -> str:
    return f"/novels/{novel_id}/jobs/{job_id}/bundles/{bundle_id}/recheck"


async def _edited_bundle(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[uuid.UUID, uuid.UUID, NovelChapter, NovelJob, str]:
    """묶음 B(둘째)+C(넷째) 에서 사용자가 B 의 블록을 직접 고친 상태."""
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _bundle_job(db_session, novel_id, chapter, base, [1, 3])
    await _edit_directly(db_client, novel_id, chapter.id, base, "둘째 문단이다.", "사용자가 고친 둘째.")
    (bundle,) = (await _edit(db_session, job.id)).bundles
    return user_id, novel_id, chapter, job, bundle.id


async def test_a_separable_verdict_frees_the_rest_so_c_applies_alone(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake: _RecheckLLM
) -> None:
    """따로 적용해도 된다는 판정이면 고친 B 를 묶음에서 빼(낡음) C 가 독립 패치가 되고, C 만 적용할 수 있다. 호출은 재검사 호출 위치
    한 번이고 고친 문단의 지금 글과 남은 수정안을 싣는다. 원장은 그대로다(무료)."""
    user_id, novel_id, chapter, job, bundle_id = await _edited_bundle(db_client, db_session, monkeypatch)
    ledger_before = await _novel_ledger(db_session, user_id)

    resp = await db_client.post(_url(novel_id, job.id, bundle_id))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"separable": True, "reason": "고친 문단에 같은 사실이 있다."}
    ((prompt, _system, usage, _schema),) = fake.calls
    assert usage.call_site == "novelize_revise_recheck"
    assert "[2] 사용자가 고친 둘째." in prompt and "[4] 고친 4." in prompt
    after = await _edit(db_session, job.id)
    assert [p.state for p in after.patches] == ["stale", "pending"]
    assert after.bundles == []
    applied = await db_client.post(
        f"/novels/{novel_id}/jobs/{job.id}/patches/apply", json={"patchId": after.patches[1].id}
    )
    assert applied.status_code == 201, applied.text
    assert split_paragraphs((await _current(db_session, chapter.id)).body)[3] == "고친 4."
    assert await _novel_ledger(db_session, user_id) == ledger_before


async def test_a_dependent_verdict_keeps_the_bundle_as_it_was(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake: _RecheckLLM
) -> None:
    """따로 적용할 수 없다는 판정이면 묶음은 그대로다 — 묶음 적용은 여전히 낡음 409, 버리기만 된다."""
    _user, novel_id, _chapter_row, job, bundle_id = await _edited_bundle(db_client, db_session, monkeypatch)
    fake.result = {"separable": False, "reason": "남은 수정안이 고치기 전 이름을 쓴다."}
    before = await _edit(db_session, job.id)

    resp = await db_client.post(_url(novel_id, job.id, bundle_id))

    assert resp.status_code == 200, resp.text
    assert resp.json()["separable"] is False
    assert (await _edit(db_session, job.id)).bundles == before.bundles


async def test_a_recheck_is_refused_without_a_reason_to_ask_and_never_calls_the_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake: _RecheckLLM
) -> None:
    """원소가 하나도 고쳐지지 않은 묶음은 409 `NOVEL_RECHECK_NOT_NEEDED`, 모르는 묶음은 404 `NOVEL_PATCH_NOT_FOUND`, 버린 작업은 409
    `NOVEL_JOB_NOT_APPLICABLE` — 모두 모델을 부르지 않고 상한도 깎지 않는다."""
    monkeypatch.setattr(settings, "novelize_recheck_hourly_limit", 1)
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _bundle_job(db_session, novel_id, chapter, base, [1, 3])
    (bundle,) = (await _edit(db_session, job.id)).bundles

    untouched = await db_client.post(_url(novel_id, job.id, bundle.id))
    unknown = await db_client.post(_url(novel_id, job.id, "nope"))
    await _edit_directly(db_client, novel_id, chapter.id, base, "둘째 문단이다.", "사용자가 고친 둘째.")
    dismissed = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/dismiss")
    assert dismissed.status_code == 204
    after_dismiss = await db_client.post(_url(novel_id, job.id, bundle.id))

    assert [(r.status_code, r.json()["detail"]) for r in (untouched, unknown, after_dismiss)] == [
        (409, {"code": "NOVEL_RECHECK_NOT_NEEDED"}),
        (404, {"code": "NOVEL_PATCH_NOT_FOUND"}),
        (409, {"code": "NOVEL_JOB_NOT_APPLICABLE"}),
    ]
    assert fake.calls == []


async def test_rechecks_past_the_hourly_cap_are_429_without_a_model_call(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake: _RecheckLLM
) -> None:
    """시간당 상한을 넘은 재검사는 429 이고 모델을 부르지 않는다. 판정을 유지한 묶음은 다시 물을 수 있어 상한이 유일한 제동이다."""
    monkeypatch.setattr(settings, "novelize_recheck_hourly_limit", 1)
    _user, novel_id, _chapter_row, job, bundle_id = await _edited_bundle(db_client, db_session, monkeypatch)
    fake.result = {"separable": False, "reason": "기댄다."}

    first = await db_client.post(_url(novel_id, job.id, bundle_id))
    second = await db_client.post(_url(novel_id, job.id, bundle_id))

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "USER_LIMIT"
    assert len(fake.calls) == 1


async def test_the_recheck_route_is_an_uncached_404_while_the_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake: _RecheckLLM
) -> None:
    """스위치를 끄면 재검사는 새 요청처럼 캐시하지 않는 404 다(적용·버리기는 그대로 된다 — `test_novelize_block_edit_apply.py`)."""
    _user, novel_id, _chapter_row, job, bundle_id = await _edited_bundle(db_client, db_session, monkeypatch)
    monkeypatch.setattr(settings, "novelize_multi_block_edit_enabled", False)

    resp = await db_client.post(_url(novel_id, job.id, bundle_id))

    assert (resp.status_code, resp.json()["detail"], resp.headers.get("cache-control")) == (
        404,
        {"code": "NOVEL_MULTI_BLOCK_EDIT_DISABLED"},
        "no-store",
    )
    assert fake.calls == []


async def test_a_change_during_the_model_call_discards_the_verdict(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake: _RecheckLLM
) -> None:
    """모델을 부르는 동안 다른 탭이 그 화를 다시 고쳤으면 판정은 옛 글에 대한 것이라 쓰지 않는다 — 409 `NOVEL_REVISION_CONFLICT`,
    묶음은 그대로."""
    _user, novel_id, chapter, job, bundle_id = await _edited_bundle(db_client, db_session, monkeypatch)
    before = await _edit(db_session, job.id)

    async def other_tab() -> None:
        current = await _current(db_session, chapter.id)
        await _edit_directly(db_client, novel_id, chapter.id, current, "첫 문단이다.", "다른 탭이 고친 첫.")

    fake.during = other_tab

    resp = await db_client.post(_url(novel_id, job.id, bundle_id))

    assert (resp.status_code, resp.json()["detail"]) == (409, {"code": "NOVEL_REVISION_CONFLICT"})
    assert (await _edit(db_session, job.id)).bundles == before.bundles


async def test_a_failed_model_call_is_503_and_keeps_the_bundle(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake: _RecheckLLM
) -> None:
    _user, novel_id, _chapter_row, job, bundle_id = await _edited_bundle(db_client, db_session, monkeypatch)
    fake.error = LLMClientError("down")
    before = await _edit(db_session, job.id)

    resp = await db_client.post(_url(novel_id, job.id, bundle_id))

    assert (resp.status_code, resp.json()["detail"]) == (503, {"code": "NOVEL_RECHECK_UNAVAILABLE"})
    assert await _edit(db_session, job.id) == before
