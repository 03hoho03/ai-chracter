"""소설 장 읽기·고치기 라우트 — 장 본문(문단), 개정 이력, 직접 수정, 되돌리기, AI 문단 수정, 수정 결과 적용.

직접 수정·되돌리기·적용은 기준 개정(`baseRevisionId`)이 장의 현재 개정과 같을 때만 새 개정을 쌓는다. 이용 제한
작품이어도, 방이 지워져도 된다(모델을 부르지 않는다). AI 문단 수정만 모델을 불러 과금·이용 제한 검사를 거친다 —
그 실행은 `test_novelize_runner.py` 에 있고 여기서는 작업을 띄우는 함수를 기록용으로 바꿔 끼운다."""

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Content, ModerationStatus, Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.novelize import router as novelize_router
from factories import (
    _NeverCalledLLMClient,
    _add_chapter,
    _clear_llm_override,
    _novel_ledger,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)

_BODY = "첫 문단이다.\n\n둘째 문단이다.\n\n셋째 문단이다."


@pytest.fixture(autouse=True)
def _no_model() -> Iterator[None]:
    """이 파일의 라우트는 모델을 직접 부르지 않는다 — 부르면 페이크가 실패시킨다."""
    _override_llm_client(_NeverCalledLLMClient())
    yield
    _clear_llm_override()


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", record)
    return seen


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


async def _restrict_and_forget_room(db: AsyncSession, novel_id: uuid.UUID) -> None:
    novel = await db.get_one(Novel, novel_id)
    await db.execute(
        sa.update(Content).where(Content.id == novel.content_id).values(moderation_status=ModerationStatus.RESTRICTED)
    )
    await db.execute(sa.update(Novel).where(Novel.id == novel_id).values(chat_room_id=None))
    await db.commit()


# ── 읽기 ────────────────────────────────────────────────────────────────────
async def test_chapter_returns_the_current_revision_split_into_paragraphs_by_the_server(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch, body="가.\n\n  \n나.\n다.\n\n라.")
    db_session.add(NovelChapterRevision(chapter_id=chapter.id, revision_no=2, body="새 가.\n\n새 나.", source="manual_edit"))
    await db_session.commit()

    resp = await db_client.get(f"/novels/{novel_id}/chapters/{chapter.id}")
    history = await db_client.get(f"/novels/{novel_id}/chapters/{chapter.id}/revisions")
    first_id = history.json()["items"][-1]["id"]
    old = await db_client.get(f"/novels/{novel_id}/chapters/{chapter.id}/revisions/{first_id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["ordinal"], body["revision"]["revisionNo"], body["revision"]["source"]) == (1, 2, "manual_edit")
    assert body["revision"]["paragraphs"] == ["새 가.", "새 나."]
    assert [(r["revisionNo"], r["source"]) for r in history.json()["items"]] == [(2, "manual_edit"), (1, "generate")]
    assert old.json()["body"] == "가.\n\n  \n나.\n다.\n\n라."
    assert old.json()["paragraphs"] == ["가.", "나.\n다.", "라."]


async def test_chapters_and_revisions_of_another_novel_or_chapter_are_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _other_user, other_novel, other_chapter = await _chapter(db_client, db_session, monkeypatch)
    other_revision = (await _revisions(db_session, other_chapter.id))[0]
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)

    foreign_chapter = await db_client.get(f"/novels/{novel_id}/chapters/{other_chapter.id}")
    foreign_revision = await db_client.get(f"/novels/{novel_id}/chapters/{chapter.id}/revisions/{other_revision.id}")
    foreign_novel = await db_client.get(f"/novels/{other_novel}/chapters/{other_chapter.id}")

    assert foreign_chapter.status_code == 404 and foreign_chapter.json()["detail"] == {"code": "NOVEL_CHAPTER_NOT_FOUND"}
    assert foreign_revision.status_code == 404
    assert foreign_revision.json()["detail"] == {"code": "NOVEL_REVISION_NOT_FOUND"}
    assert foreign_novel.status_code == 403


# ── 직접 수정 ───────────────────────────────────────────────────────────────
async def test_direct_edit_stacks_a_new_revision_with_the_whole_body(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]

    resp = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions",
        json={"baseRevisionId": str(base.id), "body": "  고친 첫 문단.\n\n\n\n둘째 문단이다.  "},
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["revision"]["paragraphs"] == ["고친 첫 문단.", "둘째 문단이다."]
    revisions = await _revisions(db_session, chapter.id)
    assert [(r.revision_no, r.source) for r in revisions] == [(1, "generate"), (2, "manual_edit")]
    assert revisions[1].body == "고친 첫 문단.\n\n둘째 문단이다."
    assert revisions[0].body == _BODY


async def test_direct_edit_on_a_stale_base_is_409_and_writes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    url = f"/novels/{novel_id}/chapters/{chapter.id}/revisions"

    first = await db_client.post(url, json={"baseRevisionId": str(base.id), "body": "탭 1"})
    second = await db_client.post(url, json={"baseRevisionId": str(base.id), "body": "탭 2"})
    blank = await db_client.post(url, json={"baseRevisionId": first.json()["revision"]["id"], "body": " \n\n "})

    assert first.status_code == 201
    assert second.status_code == 409 and second.json()["detail"] == {"code": "NOVEL_REVISION_CONFLICT"}
    assert blank.status_code == 422
    assert [r.body for r in await _revisions(db_session, chapter.id)] == [_BODY, "탭 1"]


async def test_direct_edit_and_restore_work_on_a_restricted_work_whose_room_is_gone(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    await _restrict_and_forget_room(db_session, novel_id)

    edited = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions", json={"baseRevisionId": str(base.id), "body": "고침"}
    )
    restored = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions/{base.id}/restore",
        json={"baseRevisionId": edited.json()["revision"]["id"]},
    )

    assert [edited.status_code, restored.status_code] == [201, 201]


# ── 되돌리기 ────────────────────────────────────────────────────────────────
async def test_restore_copies_an_old_revision_into_a_new_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = (await _revisions(db_session, chapter.id))[0]
    edited = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions", json={"baseRevisionId": str(first.id), "body": "고침"}
    )
    edited_id = edited.json()["revision"]["id"]
    url = f"/novels/{novel_id}/chapters/{chapter.id}/revisions/{first.id}/restore"

    stale = await db_client.post(url, json={"baseRevisionId": str(first.id)})
    restored = await db_client.post(url, json={"baseRevisionId": edited_id})

    assert stale.status_code == 409 and stale.json()["detail"] == {"code": "NOVEL_REVISION_CONFLICT"}
    assert restored.status_code == 201, restored.text
    revision = restored.json()["revision"]
    assert (revision["revisionNo"], revision["source"], revision["revertedFromRevisionId"]) == (3, "revert", str(first.id))
    assert revision["body"] == _BODY
    assert [r.revision_no for r in await _revisions(db_session, chapter.id)] == [1, 2, 3]


async def test_restoring_a_revision_of_another_chapter_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    first = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])
    second = await _add_chapter(db_session, novel_id, room, room.turns[2][0], room.turns[2][1])
    other_revision = (await _revisions(db_session, first.id))[0]
    base = (await _revisions(db_session, second.id))[0]

    resp = await db_client.post(
        f"/novels/{novel_id}/chapters/{second.id}/revisions/{other_revision.id}/restore",
        json={"baseRevisionId": str(base.id)},
    )

    assert resp.status_code == 404 and resp.json()["detail"] == {"code": "NOVEL_REVISION_NOT_FOUND"}


# ── AI 문단 수정 ────────────────────────────────────────────────────────────
async def test_ai_edit_charges_and_queues_a_job_for_the_paragraph_range(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(chat_room_id=None))
    await db_session.commit()

    resp = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/ai-edits",
        json={
            "baseRevisionId": str(base.id),
            "paragraphStart": 1,
            "paragraphEnd": 2,
            "instruction": " 더 쓸쓸하게 ",
            "expectedCost": 5,
        },
    )

    assert resp.status_code == 202, resp.text
    assert resp.json()["aiEdit"] == {
        "baseRevisionId": str(base.id),
        "paragraphStart": 1,
        "paragraphEnd": 2,
        "instruction": "더 쓸쓸하게",
        "resultText": None,
    }
    job = await db_session.get_one(NovelJob, uuid.UUID(resp.json()["id"]), populate_existing=True)
    assert (job.kind, job.chapter_id, job.status) == ("ai_edit", chapter.id, "queued")
    assert enqueued == [job.id]
    assert await _novel_ledger(db_session, user_id) == [("novelize_spend", -5)]


@pytest.mark.parametrize(
    ("change", "status_code", "code"),
    [
        pytest.param("stale_base", 409, "NOVEL_REVISION_CONFLICT", id="stale_base"),
        pytest.param("past_the_end", 422, "NOVEL_PARAGRAPH_RANGE_INVALID", id="past_the_end"),
        pytest.param("reversed", 422, "NOVEL_PARAGRAPH_RANGE_INVALID", id="reversed"),
        pytest.param("restricted", 403, "CONTENT_RESTRICTED", id="restricted"),
    ],
)
async def test_rejected_ai_edit_charges_nothing(
    change: str,
    status_code: int,
    code: str,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
) -> None:
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    payload: dict[str, Any] = {
        "baseRevisionId": str(base.id),
        "paragraphStart": 0,
        "paragraphEnd": 2,
        "instruction": "고쳐 줘",
        "expectedCost": 5,
    }
    if change == "stale_base":
        db_session.add(NovelChapterRevision(chapter_id=chapter.id, revision_no=2, body="딴 탭", source="manual_edit"))
        await db_session.commit()
    elif change == "past_the_end":
        payload["paragraphEnd"] = 3
    elif change == "reversed":
        payload["paragraphStart"] = 2
        payload["paragraphEnd"] = 1
    else:
        await _restrict_and_forget_room(db_session, novel_id)

    resp = await db_client.post(f"/novels/{novel_id}/chapters/{chapter.id}/ai-edits", json=payload)

    assert resp.status_code == status_code, resp.text
    assert resp.json()["detail"] == {"code": code}
    assert (enqueued, await _novel_ledger(db_session, user_id)) == ([], [])


# ── 적용 ────────────────────────────────────────────────────────────────────
async def _finished_ai_edit(
    db_session: AsyncSession, novel_id: uuid.UUID, chapter: NovelChapter, base: NovelChapterRevision
) -> NovelJob:
    job = NovelJob(
        novel_id=novel_id,
        user_id=(await db_session.get_one(Novel, novel_id)).user_id,
        kind="ai_edit",
        status="succeeded",
        chapter_id=chapter.id,
        base_revision_id=base.id,
        paragraph_start=1,
        paragraph_end=1,
        instruction="더 쓸쓸하게",
        result_text="첫 문단이다.\n\n쓸쓸한 둘째 문단.\n\n셋째 문단이다.",
        charged_amount=5,
    )
    db_session.add(job)
    await db_session.commit()
    return job


async def test_applying_an_ai_edit_makes_its_preview_the_new_revision_once(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    job = await _finished_ai_edit(db_session, novel_id, chapter, base)
    await _restrict_and_forget_room(db_session, novel_id)

    applied = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/apply")
    again = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/apply")
    polled = await db_client.get(f"/novels/{novel_id}/jobs/{job.id}")

    assert applied.status_code == 201, applied.text
    revision = applied.json()["revision"]
    assert (revision["revisionNo"], revision["source"]) == (2, "ai_edit")
    assert revision["paragraphs"] == ["첫 문단이다.", "쓸쓸한 둘째 문단.", "셋째 문단이다."]
    assert again.status_code == 409 and again.json()["detail"] == {"code": "NOVEL_JOB_NOT_APPLICABLE"}
    assert polled.json()["revisionId"] == revision["id"]
    assert len(await _revisions(db_session, chapter.id)) == 2


async def test_applying_onto_a_changed_chapter_is_409(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    job = await _finished_ai_edit(db_session, novel_id, chapter, base)
    await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions", json={"baseRevisionId": str(base.id), "body": "딴 탭"}
    )

    resp = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/apply")

    assert resp.status_code == 409 and resp.json()["detail"] == {"code": "NOVEL_REVISION_CONFLICT"}
    assert [r.source for r in await _revisions(db_session, chapter.id)] == ["generate", "manual_edit"]
    stored = await db_session.get_one(NovelJob, job.id, populate_existing=True)
    assert stored.result_revision_id is None


@pytest.mark.parametrize("state", ["running", "chapter_job", "failed"])
async def test_only_a_finished_ai_edit_can_be_applied(
    state: str, db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    job = await _finished_ai_edit(db_session, novel_id, chapter, base)
    states: dict[str, dict[str, Any]] = {
        "running": {"status": "running", "result_text": None},
        "chapter_job": {"kind": "chapter_generate"},
        "failed": {"status": "failed", "result_text": None},
    }
    values = states[state]
    await db_session.execute(sa.update(NovelJob).where(NovelJob.id == job.id).values(**values))
    await db_session.commit()

    resp = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/apply")

    assert resp.status_code == 409 and resp.json()["detail"] == {"code": "NOVEL_JOB_NOT_APPLICABLE"}


async def test_applying_a_job_of_another_novel_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _other_user, other_novel, other_chapter = await _chapter(db_client, db_session, monkeypatch)
    other_job = await _finished_ai_edit(
        db_session, other_novel, other_chapter, (await _revisions(db_session, other_chapter.id))[0]
    )
    _user, novel_id, _chapter_row = await _chapter(db_client, db_session, monkeypatch)

    resp = await db_client.post(f"/novels/{novel_id}/jobs/{other_job.id}/apply")

    assert resp.status_code == 404 and resp.json()["detail"] == {"code": "NOVEL_JOB_NOT_FOUND"}


# ── 미적용 AI 수정(새로고침 뒤 복구·버리기) ─────────────────────────────────
async def _pending(db_client: httpx.AsyncClient, novel_id: uuid.UUID) -> list[dict[str, Any]]:
    resp = await db_client.get(f"/novels/{novel_id}")
    assert resp.status_code == 200, resp.text
    pending: list[dict[str, Any]] = resp.json()["pendingAiEdits"]
    return pending


async def test_unapplied_ai_edit_comes_back_in_the_detail_until_it_is_applied(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """화면이 작업 id 를 잃어도(새로고침·다른 기기) 상세에서 미리보기를 다시 찾는다. 진행 중 수정은 아직 미리보기가
    없으니 싣지 않고, 적용한 수정은 더 이상 미리보기가 아니다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    job = await _finished_ai_edit(db_session, novel_id, chapter, base)

    pending = await _pending(db_client, novel_id)

    assert pending == [
        {
            "id": str(job.id),
            "chapterId": str(chapter.id),
            "paragraphStart": 1,
            "paragraphEnd": 1,
            "instruction": "더 쓸쓸하게",
            "resultText": "첫 문단이다.\n\n쓸쓸한 둘째 문단.\n\n셋째 문단이다.",
            "createdAt": pending[0]["createdAt"],
        }
    ]
    await db_session.execute(sa.update(NovelJob).where(NovelJob.id == job.id).values(status="running", result_text=None))
    await db_session.commit()
    assert await _pending(db_client, novel_id) == []

    await db_session.execute(
        sa.update(NovelJob).where(NovelJob.id == job.id).values(status="succeeded", result_text="고친 본문")
    )
    await db_session.commit()
    applied = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/apply")
    assert applied.status_code == 201, applied.text
    assert await _pending(db_client, novel_id) == []


async def test_dismissed_ai_edit_leaves_the_detail_and_can_no_longer_be_applied(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    job = await _finished_ai_edit(db_session, novel_id, chapter, base)

    dismissed = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/dismiss")
    again = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/dismiss")
    applied = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/apply")

    assert dismissed.status_code == 204, dismissed.text
    assert await _pending(db_client, novel_id) == []
    assert again.status_code == 409 and again.json()["detail"] == {"code": "NOVEL_JOB_NOT_APPLICABLE"}
    assert applied.status_code == 409 and applied.json()["detail"] == {"code": "NOVEL_JOB_NOT_APPLICABLE"}
    assert len(await _revisions(db_session, chapter.id)) == 1


@pytest.mark.parametrize("state", ["running", "applied"])
async def test_only_an_unapplied_finished_ai_edit_can_be_dismissed(
    state: str, db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    job = await _finished_ai_edit(db_session, novel_id, chapter, base)
    if state == "running":
        await db_session.execute(
            sa.update(NovelJob).where(NovelJob.id == job.id).values(status="running", result_text=None)
        )
        await db_session.commit()
    else:
        assert (await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/apply")).status_code == 201

    resp = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/dismiss")

    assert resp.status_code == 409 and resp.json()["detail"] == {"code": "NOVEL_JOB_NOT_APPLICABLE"}
    assert (await db_session.get_one(NovelJob, job.id, populate_existing=True)).dismissed_at is None


async def test_ai_edit_over_a_replaced_revision_drops_out_of_the_detail(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기준 개정이 더는 장의 현재 개정이 아니면 적용이 409 라 미리보기로 내보일 이유가 없다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    await _finished_ai_edit(db_session, novel_id, chapter, base)
    edited = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions", json={"baseRevisionId": str(base.id), "body": "딴 탭"}
    )
    assert edited.status_code == 201, edited.text

    assert await _pending(db_client, novel_id) == []


async def test_dismissing_a_job_of_another_novel_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _other_user, other_novel, other_chapter = await _chapter(db_client, db_session, monkeypatch)
    other_job = await _finished_ai_edit(
        db_session, other_novel, other_chapter, (await _revisions(db_session, other_chapter.id))[0]
    )
    _user, novel_id, _chapter_row = await _chapter(db_client, db_session, monkeypatch)

    resp = await db_client.post(f"/novels/{novel_id}/jobs/{other_job.id}/dismiss")

    assert resp.status_code == 404 and resp.json()["detail"] == {"code": "NOVEL_JOB_NOT_FOUND"}
    assert (await db_session.get_one(NovelJob, other_job.id, populate_existing=True)).dismissed_at is None


# ── 쓰지 않을 지시문·미리보기 비우기 ────────────────────────────────────────
async def _job_texts(db: AsyncSession, job_id: uuid.UUID) -> tuple[str | None, str | None]:
    job = await db.get_one(NovelJob, job_id, populate_existing=True)
    return job.instruction, job.result_text


@pytest.mark.parametrize("action", ["apply", "dismiss"])
async def test_applying_or_dismissing_an_ai_edit_erases_its_instruction_and_preview_but_keeps_the_row(
    action: str, db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """적용한 결과는 개정에, 버린 결과는 어디에도 쓸 데가 없다 — 작업 행에 지시문과 결과 사본을 남겨 둘 이유가 없다.
    행은 남는다(하루 재시도 상한을 행 수로 센다). 폴링은 그 작업에 미리보기가 없다고 답한다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    job = await _finished_ai_edit(db_session, novel_id, chapter, base)

    resp = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/{action}")
    polled = await db_client.get(f"/novels/{novel_id}/jobs/{job.id}")

    assert resp.status_code in (201, 204), resp.text
    assert await _job_texts(db_session, job.id) == (None, None)
    stored = await db_session.get_one(NovelJob, job.id, populate_existing=True)
    assert (stored.status, stored.charged_amount) == ("succeeded", 5)
    assert polled.status_code == 200, polled.text
    preview = polled.json()["aiEdit"]
    assert (preview["instruction"], preview["resultText"]) == (None, None)
    assert await _pending(db_client, novel_id) == []


@pytest.mark.parametrize("change", ["manual_edit", "revert", "apply_other"])
async def test_a_new_revision_erases_the_previews_it_made_stale_in_that_chapter_only(
    change: str, db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """장의 현재 판이 바뀌면 그 앞 판을 기준으로 한 미리보기는 적용할 수 없고 상세에도 안 나온다 — 사용자가 버리기를
    누를 길도 없으니 서버가 비운다. 다른 장의 미리보기는 그대로다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1], body=_BODY)
    other_chapter = await _add_chapter(db_session, novel_id, room, room.turns[2][0], room.turns[3][1], body=_BODY)
    base = (await _revisions(db_session, chapter.id))[0]
    stale = [await _finished_ai_edit(db_session, novel_id, chapter, base) for _ in range(2)]
    other_base = (await _revisions(db_session, other_chapter.id))[0]
    other = await _finished_ai_edit(db_session, novel_id, other_chapter, other_base)

    if change == "manual_edit":
        resp = await db_client.post(
            f"/novels/{novel_id}/chapters/{chapter.id}/revisions", json={"baseRevisionId": str(base.id), "body": "새 판"}
        )
    elif change == "revert":
        resp = await db_client.post(
            f"/novels/{novel_id}/chapters/{chapter.id}/revisions/{base.id}/restore",
            json={"baseRevisionId": str(base.id)},
        )
    else:
        resp = await db_client.post(f"/novels/{novel_id}/jobs/{stale[0].id}/apply")

    assert resp.status_code == 201, resp.text
    assert [await _job_texts(db_session, job.id) for job in stale] == [(None, None), (None, None)]
    assert await _job_texts(db_session, other.id) == (
        "더 쓸쓸하게",
        "첫 문단이다.\n\n쓸쓸한 둘째 문단.\n\n셋째 문단이다.",
    )
    assert [edit["id"] for edit in await _pending(db_client, novel_id)] == [str(other.id)]


@pytest.mark.parametrize("change", ["manual_edit", "revert", "apply"])
async def test_a_committed_revision_stays_201_when_erasing_stale_previews_fails(
    change: str, db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """새 개정은 이미 커밋됐다. 그 뒤의 비우기가 DB 오류로 실패해도 응답이 500 이면 화면은 저장 실패로 보고 같은 기준으로
    다시 보내 409 를 받는다 — 성공한 수정이 "다른 탭이 먼저 고쳤다"로 보인다. 비우기는 다음 개정 때 다시 돌므로 삼키고
    남기기만 한다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1], body=_BODY)
    base = (await _revisions(db_session, chapter.id))[0]
    pending = await _finished_ai_edit(db_session, novel_id, chapter, base)

    async def broken_erase(db: AsyncSession, _chapter_id: uuid.UUID) -> None:
        await db.execute(sa.text("SELECT 1 / 0"))  # 트랜잭션을 깨진 상태로 만든다(롤백 없이는 다음 조회도 실패)

    reported: list[str] = []
    monkeypatch.setattr(novelize_router, "erase_stale_ai_edit_previews", broken_erase)
    monkeypatch.setattr(
        novelize_router, "capture_dependency_failure", lambda _exc, *, dependency: reported.append(dependency)
    )

    if change == "manual_edit":
        resp = await db_client.post(
            f"/novels/{novel_id}/chapters/{chapter.id}/revisions", json={"baseRevisionId": str(base.id), "body": "새 판"}
        )
    elif change == "revert":
        resp = await db_client.post(
            f"/novels/{novel_id}/chapters/{chapter.id}/revisions/{base.id}/restore",
            json={"baseRevisionId": str(base.id)},
        )
    else:
        resp = await db_client.post(f"/novels/{novel_id}/jobs/{pending.id}/apply")

    assert resp.status_code == 201, resp.text
    assert resp.json()["revision"]["revisionNo"] == 2
    assert [r.revision_no for r in await _revisions(db_session, chapter.id)] == [1, 2]
    assert reported == ["db"]


async def test_detail_skips_a_preview_whose_text_was_erased_instead_of_failing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상세는 목차(현재 판)와 미리보기를 서로 다른 문장으로 읽는다. 그 사이 새 판이 생겨 미리보기가 비워지면 기준
    판은 아직 목차의 현재 판인데 본문은 없는 행을 보게 된다 — 500 이 아니라 목록에서 빼야 한다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = (await _revisions(db_session, chapter.id))[0]
    job = await _finished_ai_edit(db_session, novel_id, chapter, base)
    await db_session.execute(
        sa.update(NovelJob).where(NovelJob.id == job.id).values(instruction=None, result_text=None)
    )
    await db_session.commit()

    assert await _pending(db_client, novel_id) == []
