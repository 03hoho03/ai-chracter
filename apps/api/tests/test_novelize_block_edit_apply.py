"""여러 문단 수정의 수정안 적용·버리기(`POST /novels/{id}/jobs/{jobId}/patches/apply`·`.../patches/dismiss`), 새 개정 뒤 패치
단위 낡음 비우기, 환불·버리기의 기준 해시 지우기.

끝난 패치 작업은 행을 직접 넣는다(실행은 `test_novelize_block_edit_runner.py`). 적용·버리기는 여러 문단 수정 스위치와 무관하다 —
켰다 끈 뒤에도 이미 받은 수정안을 쓰거나 버릴 수 있어야 한다."""

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import Asset, AssetKind, AssetStatus, Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.db.models.novel import NovelChapterIllustration
from api.novelize import billing
from api.novelize import router as novelize_router
from api.novelize.block_edits import BlockEdit, block_hash, normalized_result, request_targets
from api.novelize.schemas import CHAPTER_BODY_MAX_LENGTH
from api.novelize.text import split_paragraphs
from factories import (
    _NeverCalledLLMClient,
    _add_chapter,
    _clear_llm_override,
    _novel_ledger,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_BODY = "첫 문단이다.\n\n둘째 문단이다.\n\n셋째 문단이다.\n\n넷째 문단이다."


@pytest.fixture(autouse=True)
def _no_model() -> Iterator[None]:
    _override_llm_client(_NeverCalledLLMClient())
    yield
    _clear_llm_override()


@pytest.fixture(autouse=True)
def _switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """적용·버리기는 스위치를 보지 않는다 — 꺼 둔 채로 시험해 끈 뒤에도 동작함을 늘 같이 본다."""
    monkeypatch.setattr(settings, "novelize_multi_block_edit_enabled", False)


async def _chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, body: str = _BODY
) -> tuple[uuid.UUID, uuid.UUID, NovelChapter]:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1], body=body)
    return room.user_id, novel_id, chapter


async def _revisions(db: AsyncSession, chapter_id: uuid.UUID) -> list[NovelChapterRevision]:
    rows = await db.scalars(
        sa.select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _current(db: AsyncSession, chapter_id: uuid.UUID) -> NovelChapterRevision:
    return (await _revisions(db, chapter_id))[-1]


async def _job(db: AsyncSession, job_id: uuid.UUID) -> NovelJob:
    job = await db.scalar(sa.select(NovelJob).where(NovelJob.id == job_id).execution_options(populate_existing=True))
    assert job is not None
    return job


async def _patch_job(
    db: AsyncSession,
    novel_id: uuid.UUID,
    chapter: NovelChapter,
    base: NovelChapterRevision,
    positions: list[int],
    *,
    bundles: list[list[int]] | None = None,
    texts: dict[int, list[str]] | None = None,
    **overrides: object,
) -> NovelJob:
    """`positions` 문단마다 패치(기본 "고친 n.", `texts` 로 바꿈)를 가진 끝난 패치 작업. `bundles` 는 위치 목록의 묶음."""
    paragraphs = split_paragraphs(base.body)
    targets = request_targets([base.block_ids[i] for i in positions], base.block_ids, paragraphs)
    patches, patch_bundles, _ = normalized_result(
        targets,
        [(i + 1, (texts or {}).get(i, [f"고친 {i + 1}."])) for i in positions],
        [([i + 1 for i in members], "앞이 정한 사실을 뒤가 쓴다") for members in bundles or []],
    )
    values: dict[str, object] = {
        "novel_id": novel_id,
        "user_id": (await db.get_one(Novel, novel_id)).user_id,
        "kind": "ai_edit",
        "status": "succeeded",
        "chapter_id": chapter.id,
        "base_revision_id": base.id,
        "instruction": "더 쓸쓸하게",
        "charged_amount": 20,
        "block_edit": BlockEdit(targets=targets, scene_id=None, patches=patches, bundles=patch_bundles).to_json(),
    }
    values.update(overrides)
    job = NovelJob(**values)
    db.add(job)
    await db.commit()
    return job


def _edit(job: NovelJob) -> BlockEdit:
    assert job.block_edit is not None
    return BlockEdit.model_validate(job.block_edit)


async def _apply(client: httpx.AsyncClient, novel_id: uuid.UUID, job_id: uuid.UUID, **unit: object) -> httpx.Response:
    return await client.post(f"/novels/{novel_id}/jobs/{job_id}/patches/apply", json=unit)


async def _dismiss(client: httpx.AsyncClient, novel_id: uuid.UUID, job_id: uuid.UUID, **unit: object) -> httpx.Response:
    return await client.post(f"/novels/{novel_id}/jobs/{job_id}/patches/dismiss", json=unit)


def _code(resp: httpx.Response) -> tuple[int, object]:
    return resp.status_code, resp.json().get("detail")


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


# ── 적용 ────────────────────────────────────────────────────────────────────
async def test_an_independent_patch_applies_alone_and_the_bundle_keeps_waiting(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """독립 패치 A 만 적용하면 새 개정 하나에 A 의 블록만 바뀌고(나머지 문단·블록 id 는 자리째 같다) 묶음 B+C 는 대기 그대로 상세에
    남는다. A 는 적용·문단 없음·적용 개정 id, 작업의 결과 개정은 그 개정, 지시문은 남은 수정안이 있어 남는다. 원장은 그대로다(적용은
    무료). 스위치가 꺼져 있어도 된다(N-Q12 독립 A 단독)."""
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [0, 1, 2], bundles=[[1, 2]])
    alone = _edit(job).patches[0]
    ledger_before = await _novel_ledger(db_session, user_id)

    resp = await _apply(db_client, novel_id, job.id, patchId=alone.id)

    assert resp.status_code == 201, resp.text
    current = await _current(db_session, chapter.id)
    assert (current.revision_no, current.source) == (2, "ai_edit")
    assert split_paragraphs(current.body) == ["고친 1.", "둘째 문단이다.", "셋째 문단이다.", "넷째 문단이다."]
    assert current.block_ids == base.block_ids
    stored = await _job(db_session, job.id)
    after = _edit(stored)
    assert [(p.state, p.paragraphs, p.revision_id) for p in after.patches] == [
        ("applied", None, current.id),
        ("pending", ["고친 2."], None),
        ("pending", ["고친 3."], None),
    ]
    assert (stored.result_revision_id, stored.instruction, stored.dismissed_at) == (current.id, "더 쓸쓸하게", None)
    (listed,) = (await db_client.get(f"/novels/{novel_id}")).json()["pendingBlockEdits"]
    assert [(p["state"], p["fresh"]) for p in listed["patches"]] == [
        ("applied", False),
        ("pending", True),
        ("pending", True),
    ]
    assert await _novel_ledger(db_session, user_id) == ledger_before


async def test_a_bundle_applies_in_one_revision_and_the_last_unit_erases_the_instruction(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """묶음은 원소 전부를 개정 하나로 적용한다. 마지막 단위를 적용해 대기 수정안이 없어지면 지시문과 묶음 이유를 비우고 상세 목록에서
    빠진다(처리방침의 즉시 삭제)."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [1, 3], bundles=[[1, 3]])
    (bundle,) = _edit(job).bundles

    resp = await _apply(db_client, novel_id, job.id, bundleId=bundle.id)

    assert resp.status_code == 201, resp.text
    revisions = await _revisions(db_session, chapter.id)
    assert [r.revision_no for r in revisions] == [1, 2]
    assert split_paragraphs(revisions[-1].body) == ["첫 문단이다.", "고친 2.", "셋째 문단이다.", "고친 4."]
    stored = await _job(db_session, job.id)
    assert stored.instruction is None and stored.dismissed_at is None
    assert [b.reason for b in _edit(stored).bundles] == [None]
    assert (await db_client.get(f"/novels/{novel_id}")).json()["pendingBlockEdits"] == []


async def test_a_bundle_with_an_edited_member_is_refused_whole(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """묶음 B+C 에서 사용자가 B 의 블록을 직접 고쳤으면 묶음 적용은 409 `NOVEL_PATCH_STALE`(낡은 원소 id 에 B)이고 아무것도 쓰지
    않는다 — 개정 수와 C 블록의 글이 그대로다(N-Q12 B+C 원자)."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [1, 2], bundles=[[1, 2]])
    b_patch, _c_patch = _edit(job).patches
    (bundle,) = _edit(job).bundles
    await _edit_directly(db_client, novel_id, chapter.id, base, "둘째 문단이다.", "사용자가 고친 둘째.")
    edited = await _current(db_session, chapter.id)

    resp = await _apply(db_client, novel_id, job.id, bundleId=bundle.id)

    assert _code(resp) == (409, {"code": "NOVEL_PATCH_STALE", "stalePatchIds": [b_patch.id]})
    current = await _current(db_session, chapter.id)
    assert current.id == edited.id
    assert split_paragraphs(current.body)[2] == "셋째 문단이다."


async def test_a_patch_never_overwrites_a_block_another_job_already_changed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """두 작업이 같은 블록에 수정안을 냈으면 앞 것을 적용한 뒤 뒤 것은 409 `NOVEL_PATCH_STALE` 이고, 새 개정 뒤 비우기가 뒤 작업의
    그 패치를 낡음(문단 없음)으로 바꾼다. 다른 블록의 패치는 대기 그대로다(N-Q13 덮어쓰기 0)."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    first = await _patch_job(db_session, novel_id, chapter, base, [1], texts={1: ["앞 작업의 둘째."]})
    second = await _patch_job(db_session, novel_id, chapter, base, [1, 3], texts={1: ["뒤 작업의 둘째."]})
    overlapping, other = _edit(second).patches

    assert (await _apply(db_client, novel_id, first.id, patchId=_edit(first).patches[0].id)).status_code == 201
    resp = await _apply(db_client, novel_id, second.id, patchId=overlapping.id)

    assert _code(resp) == (409, {"code": "NOVEL_PATCH_STALE", "stalePatchIds": [overlapping.id]})
    assert split_paragraphs((await _current(db_session, chapter.id)).body)[1] == "앞 작업의 둘째."
    after = _edit(await _job(db_session, second.id))
    assert [(p.id, p.state, p.paragraphs) for p in after.patches] == [
        (overlapping.id, "stale", None),
        (other.id, "pending", ["고친 4."]),
    ]


async def test_a_later_patch_still_applies_when_the_earlier_one_kept_the_original_paragraph(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """앞 작업의 패치가 원래 문단을 글자 그대로 남기고 앞에 문단을 더했으면 그 문단이 블록 id 와 글을 지켜 뒤 작업의 패치가 적용된다 —
    덮어쓰기가 아니라 원래 문단만 바뀌고, 앞 작업이 더한 문단은 남는다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    first = await _patch_job(db_session, novel_id, chapter, base, [1], texts={1: ["앞에 더한 문단.", "둘째 문단이다."]})
    second = await _patch_job(db_session, novel_id, chapter, base, [1], texts={1: ["뒤 작업의 둘째."]})

    assert (await _apply(db_client, novel_id, first.id, patchId=_edit(first).patches[0].id)).status_code == 201
    resp = await _apply(db_client, novel_id, second.id, patchId=_edit(second).patches[0].id)

    assert resp.status_code == 201, resp.text
    current = await _current(db_session, chapter.id)
    assert split_paragraphs(current.body) == [
        "첫 문단이다.",
        "앞에 더한 문단.",
        "뒤 작업의 둘째.",
        "셋째 문단이다.",
        "넷째 문단이다.",
    ]
    assert current.block_ids[2] == base.block_ids[1]


@pytest.mark.parametrize(("extra", "expected"), [(0, 201), (1, 409)])
async def test_an_apply_that_would_pass_the_chapter_length_cap_is_refused(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    extra: int,
    expected: int,
) -> None:
    """적용한 화 본문이 직접 수정 상한(10만 자)을 넘게 되면 409 `NOVEL_CHAPTER_TOO_LONG` + `maxChars` 이고 아무것도 쓰지 않는다 —
    넘긴 화는 그 뒤 직접 수정이 늘 거절된다. 상한과 같은 길이는 된다."""
    long_paragraph = "가" * (CHAPTER_BODY_MAX_LENGTH - 100)
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch, body=f"{long_paragraph}\n\n짧다.")
    base = await _current(db_session, chapter.id)
    replacement = "나" * (100 - 2 + extra)
    job = await _patch_job(db_session, novel_id, chapter, base, [1], texts={1: [replacement]})

    resp = await _apply(db_client, novel_id, job.id, patchId=_edit(job).patches[0].id)

    assert resp.status_code == expected, resp.text
    if expected == 409:
        assert resp.json()["detail"] == {"code": "NOVEL_CHAPTER_TOO_LONG", "maxChars": CHAPTER_BODY_MAX_LENGTH}
        assert (await _current(db_session, chapter.id)).id == base.id
        assert _edit(await _job(db_session, job.id)).patches[0].state == "pending"
    else:
        assert len((await _current(db_session, chapter.id)).body) == CHAPTER_BODY_MAX_LENGTH


async def test_apply_refuses_what_is_not_an_applicable_unit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """적용할 수 없는 것: 다른 소설의 작업·없는 작업 404, 옛 연속 범위 작업·버린 작업 409 `NOVEL_JOB_NOT_APPLICABLE`, 모르는 패치·묶음
    404 `NOVEL_PATCH_NOT_FOUND`, 묶음에 든 패치를 혼자·이미 적용한 패치 409, 패치와 묶음을 둘 다 또는 하나도 안 보냄 422. 어느 것도
    개정을 쌓지 않는다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [0, 1, 2], bundles=[[1, 2]])
    alone, bundled, _ = _edit(job).patches
    (bundle,) = _edit(job).bundles
    dropped = await _patch_job(db_session, novel_id, chapter, base, [3], dismissed_at=sa.func.now())
    old = NovelJob(
        novel_id=novel_id,
        user_id=(await db_session.get_one(Novel, novel_id)).user_id,
        kind="ai_edit",
        status="succeeded",
        chapter_id=chapter.id,
        base_revision_id=base.id,
        paragraph_start=0,
        paragraph_end=0,
        instruction="x",
        result_text="새 첫 문단.\n\n둘째 문단이다.\n\n셋째 문단이다.\n\n넷째 문단이다.",
        charged_amount=20,
    )
    db_session.add(old)
    await db_session.commit()

    results = [
        _code(await _apply(db_client, novel_id, uuid.uuid4(), patchId=alone.id)),
        _code(await _apply(db_client, novel_id, old.id, patchId="p")),
        _code(await _apply(db_client, novel_id, dropped.id, patchId=_edit(dropped).patches[0].id)),
        _code(await _apply(db_client, novel_id, job.id, patchId="nope")),
        _code(await _apply(db_client, novel_id, job.id, bundleId="nope")),
        _code(await _apply(db_client, novel_id, job.id, patchId=bundled.id)),
    ]
    both = await _apply(db_client, novel_id, job.id, patchId=alone.id, bundleId=bundle.id)
    neither = await _apply(db_client, novel_id, job.id)
    assert (await _apply(db_client, novel_id, job.id, patchId=alone.id)).status_code == 201
    again = _code(await _apply(db_client, novel_id, job.id, patchId=alone.id))

    assert results == [
        (404, {"code": "NOVEL_JOB_NOT_FOUND"}),
        (409, {"code": "NOVEL_JOB_NOT_APPLICABLE"}),
        (409, {"code": "NOVEL_JOB_NOT_APPLICABLE"}),
        (404, {"code": "NOVEL_PATCH_NOT_FOUND"}),
        (404, {"code": "NOVEL_PATCH_NOT_FOUND"}),
        (409, {"code": "NOVEL_JOB_NOT_APPLICABLE"}),
    ]
    assert (both.status_code, neither.status_code) == (422, 422)
    assert again == (409, {"code": "NOVEL_JOB_NOT_APPLICABLE"})
    assert [r.revision_no for r in await _revisions(db_session, chapter.id)] == [1, 2]


async def test_an_illustration_anchored_to_the_patched_block_stays_on_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """패치가 블록을 두 문단으로 나눠도 그 블록 뒤에 붙인 삽화는 블록 id 를 이은 첫 문단에 그대로 붙어 있다(위치 확인 필요로 빠지지
    않는다)."""
    monkeypatch.setattr(settings, "novel_illustrations_enabled", True)
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    asset = Asset(
        owner_user_id=user_id,
        storage_key=f"assets/novel-illustration/{uuid.uuid4()}.webp",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
        width=300,
        height=400,
    )
    db_session.add(asset)
    await db_session.commit()
    attached = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/illustrations",
        json={
            "baseRevisionId": str(base.id),
            "anchorBlockId": str(base.block_ids[1]),
            "placement": "after",
            "assetId": str(asset.id),
            "source": "upload",
        },
    )
    assert attached.status_code == 201, attached.text
    with_picture = await _current(db_session, chapter.id)
    job = await _patch_job(
        db_session, novel_id, chapter, with_picture, [1], texts={1: ["나눈 앞 문단.", "나눈 뒤 문단."]}
    )

    resp = await _apply(db_client, novel_id, job.id, patchId=_edit(job).patches[0].id)

    assert resp.status_code == 201, resp.text
    current = await _current(db_session, chapter.id)
    anchors = (
        await db_session.scalars(
            sa.select(NovelChapterIllustration.anchor_block_id).where(
                NovelChapterIllustration.revision_id == current.id
            )
        )
    ).all()
    assert list(anchors) == [base.block_ids[1]]
    assert current.block_ids[1] == base.block_ids[1]


# ── 버리기 ──────────────────────────────────────────────────────────────────
async def test_dismissing_units_drops_their_text_and_hashes_and_the_last_one_erases_the_instruction(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """독립 패치·묶음을 하나씩 버리면 그 패치는 버림·문단 없음이고 그 블록의 기준 해시(대상·패치)가 지워진다. 남은 패치의 해시는
    그대로다. 마지막 단위를 버리면 지시문·묶음 이유를 비운다. "전부 버리기"가 아니라 버린 시각은 찍지 않는다. 환불은 없다."""
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [0, 1, 2], bundles=[[1, 2]])
    alone = _edit(job).patches[0]
    (bundle,) = _edit(job).bundles
    ledger_before = await _novel_ledger(db_session, user_id)

    first = await _dismiss(db_client, novel_id, job.id, patchId=alone.id)
    middle = _edit(await _job(db_session, job.id))
    second = await _dismiss(db_client, novel_id, job.id, bundleId=bundle.id)

    assert (first.status_code, second.status_code) == (204, 204)
    assert [(p.state, p.base_hash) for p in middle.patches] == [
        ("dismissed", ""),
        ("pending", block_hash("둘째 문단이다.")),
        ("pending", block_hash("셋째 문단이다.")),
    ]
    assert [t.base_hash for t in middle.targets] == ["", block_hash("둘째 문단이다."), block_hash("셋째 문단이다.")]
    stored = await _job(db_session, job.id)
    after = _edit(stored)
    assert [(p.state, p.paragraphs, p.base_hash) for p in after.patches] == [("dismissed", None, "")] * 3
    assert [t.base_hash for t in after.targets] == [""] * 3
    assert [b.reason for b in after.bundles] == [None]
    assert (stored.instruction, stored.dismissed_at) == (None, None)
    assert await _novel_ledger(db_session, user_id) == ledger_before


async def test_dismissing_everything_marks_the_job_dismissed_even_after_a_partial_apply(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "전부 버리기"는 일부를 적용한 작업에도 된다 — 남은 대기·낡음 패치를 버림으로, 버린 시각을 찍고 지시문·문단·기준 해시를 모두
    지운다. 적용한 패치는 적용 상태로 남는다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [0, 2])
    applied, _ = _edit(job).patches
    assert (await _apply(db_client, novel_id, job.id, patchId=applied.id)).status_code == 201

    resp = await _dismiss(db_client, novel_id, job.id, all=True)

    assert resp.status_code == 204, resp.text
    stored = await _job(db_session, job.id)
    after = _edit(stored)
    assert [(p.state, p.paragraphs, p.base_hash) for p in after.patches] == [
        ("applied", None, ""),
        ("dismissed", None, ""),
    ]
    assert [t.base_hash for t in after.targets] == ["", ""]
    assert stored.dismissed_at is not None and stored.instruction is None
    assert _code(await _dismiss(db_client, novel_id, job.id, all=True)) == (409, {"code": "NOVEL_JOB_NOT_APPLICABLE"})


async def test_dismissing_everything_is_refused_when_nothing_is_left_to_dismiss(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """수정안을 모두 적용한 작업에는 버릴 것이 없다 — 409 이고 버린 시각을 찍지 않는다(적용 기록이 "버림"으로 읽히지 않게)."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [0])
    assert (await _apply(db_client, novel_id, job.id, patchId=_edit(job).patches[0].id)).status_code == 201

    resp = await _dismiss(db_client, novel_id, job.id, all=True)

    assert _code(resp) == (409, {"code": "NOVEL_JOB_NOT_APPLICABLE"})
    assert (await _job(db_session, job.id)).dismissed_at is None


async def test_dismiss_refuses_a_bundled_patch_alone_and_unknown_ids(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [1, 2], bundles=[[1, 2]])
    bundled = _edit(job).patches[0]

    assert _code(await _dismiss(db_client, novel_id, job.id, patchId=bundled.id)) == (
        409,
        {"code": "NOVEL_JOB_NOT_APPLICABLE"},
    )
    assert _code(await _dismiss(db_client, novel_id, job.id, patchId="nope")) == (
        404,
        {"code": "NOVEL_PATCH_NOT_FOUND"},
    )
    assert (await _dismiss(db_client, novel_id, job.id, patchId=bundled.id, all=True)).status_code == 422
    assert _edit(await _job(db_session, job.id)) == _edit(job)


async def test_the_old_dismiss_also_drops_every_base_hash(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """옛 화면의 버리기(작업 단위)도 패치 작업이면 전부 버리기다 — 기준 해시까지 지운다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [0, 1])

    resp = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/dismiss")

    assert resp.status_code == 204
    after = _edit(await _job(db_session, job.id))
    assert [p.base_hash for p in after.patches] == ["", ""]
    assert [t.base_hash for t in after.targets] == ["", ""]


# ── 새 개정 뒤 비우기 ───────────────────────────────────────────────────────
async def test_a_direct_edit_turns_only_that_block_patch_stale_for_good(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """사용자가 블록 하나를 직접 고치면 새 개정 뒤 비우기가 그 블록의 대기 패치만 낡음(문단 없음)으로 바꾸고, 같은 작업의 다른 패치와
    지시문은 그대로다. 같은 글로 되돌려도 되살리지 않는다. 다른 패치의 블록까지 고치면 대기 수정안이 없어져 지시문을 비운다. 깨지는
    시나리오: 고친 블록의 수정안 문단이 행에 영영 남거나, 블록 하나를 고쳤다고 같은 작업의 다른 수정안이 사라진다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [0, 2])

    async def snapshot() -> tuple[list[tuple[str, list[str] | None]], str | None]:
        # 같은 행 객체를 다시 읽으면 값이 바뀌므로 그때그때 값을 떠 둔다.
        stored = await _job(db_session, job.id)
        return [(p.state, p.paragraphs) for p in _edit(stored).patches], stored.instruction

    await _edit_directly(db_client, novel_id, chapter.id, base, "첫 문단이다.", "사용자가 고친 첫 문단.")
    after_first = await snapshot()
    reverted = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions/{base.id}/restore",
        json={"baseRevisionId": str((await _current(db_session, chapter.id)).id)},
    )
    assert reverted.status_code == 201, reverted.text
    after_revert = await snapshot()
    await _edit_directly(
        db_client, novel_id, chapter.id, await _current(db_session, chapter.id), "셋째 문단이다.", "사용자가 고친 셋째."
    )
    after_both = await snapshot()

    assert after_first == ([("stale", None), ("pending", ["고친 3."])], "더 쓸쓸하게")
    assert after_revert == after_first
    assert after_both == ([("stale", None), ("stale", None)], None)


# ── 환불 ────────────────────────────────────────────────────────────────────
async def test_a_refunded_patch_job_keeps_no_base_hash(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실패·환불한 패치 작업은 대상의 블록 id·번호만 남기고 기준 해시를 지운다 — 짧은 문단은 해시에서 글을 되찾을 수 있다."""
    monkeypatch.setattr(settings, "novelize_multi_block_edit_enabled", True)
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", record)
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    created = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/block-edits",
        json={
            "baseRevisionId": str(base.id),
            "blockIds": [str(base.block_ids[0]), str(base.block_ids[2])],
            "instruction": "더 쓸쓸하게",
            "expectedCost": 20,
        },
    )
    assert created.status_code == 202, created.text
    (job_id,) = seen

    refunded = await billing.refund_job(db_session, job_id=job_id, failure_code="llm_error")
    await db_session.commit()

    assert refunded == 20
    stored = await _job(db_session, job_id)
    assert stored.instruction is None
    assert [(t.block_id, t.label, t.base_hash) for t in _edit(stored).targets] == [
        (base.block_ids[0], 1, ""),
        (base.block_ids[2], 3, ""),
    ]
