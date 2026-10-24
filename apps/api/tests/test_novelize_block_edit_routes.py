"""여러 문단 수정 요청 라우트(`POST /novels/{id}/chapters/{cid}/block-edits`)와 그 작업이 옛 경로(상세의 미적용 목록·옛 적용·옛
버리기·마지막 묶음 삭제·낡은 미리보기 비우기)와 만나는 자리.

실행(모델 호출·저장)은 `test_novelize_block_edit_runner.py` 에 있고, 여기서는 작업을 띄우는 함수를 기록용으로 바꿔 끼운다. 끝난
패치 작업이 필요한 테스트는 행을 직접 넣는다."""

import ast
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import (
    Content,
    ModerationStatus,
    Novel,
    NovelChapter,
    NovelChapterRevision,
    NovelEpisodeOutline,
    NovelJob,
    NovelOutline,
    NovelSceneBlock,
)
from api.novelize import router as novelize_router
from api.novelize.block_edits import BlockEdit, block_hash, normalized_result, request_targets
from api.novelize.blocks import build_revision
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


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", record)
    return seen


@pytest.fixture
def switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_multi_block_edit_enabled", True)


async def _chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, body: str = _BODY
) -> tuple[uuid.UUID, uuid.UUID, NovelChapter]:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1], body=body)
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


async def _jobs(db: AsyncSession, novel_id: uuid.UUID) -> list[NovelJob]:
    rows = await db.scalars(
        sa.select(NovelJob)
        .where(NovelJob.novel_id == novel_id)
        .order_by(NovelJob.created_at)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


def _request(base: NovelChapterRevision, positions: list[int], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "baseRevisionId": str(base.id),
        "blockIds": [str(base.block_ids[i]) for i in positions],
        "instruction": "더 쓸쓸하게",
        "expectedCost": 20,
    }
    payload.update(overrides)
    return payload


def _url(novel_id: uuid.UUID, chapter_id: uuid.UUID) -> str:
    return f"/novels/{novel_id}/chapters/{chapter_id}/block-edits"


def _code(resp: httpx.Response) -> tuple[int, object]:
    return resp.status_code, resp.json().get("detail")


# ── 스위치 ──────────────────────────────────────────────────────────────────
async def test_the_block_edit_route_is_an_uncached_404_while_the_switch_is_off_and_the_old_edit_still_runs(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID]
) -> None:
    """스위치가 꺼져 있으면 새 요청은 캐시하지 않는 404 `NOVEL_MULTI_BLOCK_EDIT_DISABLED` 이고 작업·원장이 생기지 않는다. 옛 연속
    범위 요청은 그대로 받아 차감한다. 깨지는 시나리오: 꺼진 채 배포한 동안 패치 작업이 생기거나(적용 경로가 없다), 켠 뒤에도 캐시된
    404 가 남거나, 옛 요청이 막힌다."""
    monkeypatch.setattr(settings, "novelize_multi_block_edit_enabled", False)
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)

    refused = await db_client.post(_url(novel_id, chapter.id), json=_request(base, [0, 2]))
    jobs_after_refusal = await _jobs(db_session, novel_id)
    old = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/ai-edits",
        json={"baseRevisionId": str(base.id), "paragraphStart": 1, "paragraphEnd": 2, "instruction": "x", "expectedCost": 20},
    )

    assert (_code(refused), refused.headers.get("cache-control")) == (
        (404, {"code": "NOVEL_MULTI_BLOCK_EDIT_DISABLED"}),
        "no-store",
    )
    assert jobs_after_refusal == []
    assert old.status_code == 202, old.text
    (job,) = await _jobs(db_session, novel_id)
    assert (job.paragraph_start, job.paragraph_end, job.block_edit) == (1, 2, None)
    assert await _novel_ledger(db_session, user_id) == [("novelize_spend", -20)]


# ── 요청 ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("count", [1, 5, 20])
async def test_a_block_edit_is_one_charge_whatever_the_block_count(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    switch_on: None,
    count: int,
) -> None:
    """블록 1·5·20 개 요청 모두 AI 수정 단가 한 번 = 원장 한 줄이다. 작업은 `ai_edit` 이고 패치 작업이라 범위·결과 본문 칸은
    비어 있으며(옛 목록·옛 적용이 이 행을 거른다), 대상은 본문 차례로 블록 id·기준 해시·문단 번호를 적는다. 장면 없는 화라 장면은
    null(화 전체)이다."""
    body = "\n\n".join(f"{n}번째 문단이다." for n in range(1, 21))
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch, body=body)
    base = await _current(db_session, chapter.id)
    positions = list(range(20 - count, 20))[::-1]

    resp = await db_client.post(_url(novel_id, chapter.id), json=_request(base, positions))

    assert resp.status_code == 202, resp.text
    assert resp.headers.get("cache-control") == "no-store"
    (job,) = await _jobs(db_session, novel_id)
    assert enqueued == [job.id]
    assert resp.json()["id"] == str(job.id) and resp.json()["kind"] == "ai_edit"
    assert (job.kind, job.chapter_id, job.base_revision_id, job.instruction) == ("ai_edit", chapter.id, base.id, "더 쓸쓸하게")
    assert (job.paragraph_start, job.paragraph_end, job.result_text) == (None, None, None)
    assert job.block_edit is not None
    paragraphs = split_paragraphs(body)
    assert job.block_edit["targets"] == [
        {"blockId": str(base.block_ids[i]), "baseHash": block_hash(paragraphs[i]), "label": i + 1}
        for i in sorted(positions)
    ]
    assert (job.block_edit["sceneId"], job.block_edit["patches"], job.block_edit["bundles"]) == (None, [], [])
    assert await _novel_ledger(db_session, user_id) == [("novelize_spend", -20)]


async def test_a_stale_base_revision_is_409_before_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID], switch_on: None
) -> None:
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    edited = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions",
        json={"baseRevisionId": str(base.id), "body": _BODY.replace("둘째", "고친 둘째")},
    )
    assert edited.status_code == 201

    resp = await db_client.post(_url(novel_id, chapter.id), json=_request(base, [0]))

    assert _code(resp) == (409, {"code": "NOVEL_REVISION_CONFLICT"})
    assert (await _jobs(db_session, novel_id), enqueued) == ([], [])
    assert await _novel_ledger(db_session, user_id) == []


async def test_unknown_duplicate_or_too_many_blocks_are_422_before_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID], switch_on: None
) -> None:
    """기준 개정에 없는 블록·같은 블록 둘·빈 목록은 422 `NOVEL_BLOCK_IDS_INVALID`, 상한(20)을 넘으면 422 `NOVEL_TOO_MANY_BLOCKS` +
    `maxBlocks` 다. 상한은 상세의 `limits.blockEditMaxBlocks` 와 같다. 모두 차감 전이다."""
    body = "\n\n".join(f"{n}번째 문단이다." for n in range(1, 23))
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch, body=body)
    base = await _current(db_session, chapter.id)
    url = _url(novel_id, chapter.id)

    unknown = await db_client.post(url, json=_request(base, [0], blockIds=[str(base.block_ids[0]), str(uuid.uuid4())]))
    duplicate = await db_client.post(url, json=_request(base, [0, 0]))
    empty = await db_client.post(url, json=_request(base, []))
    too_many = await db_client.post(url, json=_request(base, list(range(21))))
    detail = await db_client.get(f"/novels/{novel_id}")

    assert [_code(r) for r in (unknown, duplicate)] == [(422, {"code": "NOVEL_BLOCK_IDS_INVALID"})] * 2
    assert empty.status_code == 422
    assert _code(too_many) == (422, {"code": "NOVEL_TOO_MANY_BLOCKS", "maxBlocks": 20})
    assert detail.json()["limits"]["blockEditMaxBlocks"] == 20
    assert (await _jobs(db_session, novel_id), enqueued) == ([], [])
    assert await _novel_ledger(db_session, user_id) == []


async def _scene_rows(db: AsyncSession, novel_id: uuid.UUID, chapter: NovelChapter, scene_of: dict[uuid.UUID, str]) -> None:
    """화 `chapter` 의 블록에 장면 행을 넣는다(구성 흐름 원고가 쓴 경계 흉내)."""
    outline = NovelOutline(novel_id=novel_id, revision=1, source="generate", selection_id=uuid.uuid4(), episodes=[])
    db.add(outline)
    await db.flush()
    episode = NovelEpisodeOutline(
        novel_id=novel_id, outline_id=outline.id, episode_key=uuid.uuid4(), revision=1, source="generate", scenes=[]
    )
    db.add(episode)
    await db.flush()
    db.add_all(
        NovelSceneBlock(block_id=block_id, chapter_id=chapter.id, episode_outline_id=episode.id, scene_id=scene)
        for block_id, scene in scene_of.items()
    )
    await db.commit()


async def test_blocks_must_share_one_scene_where_rowless_blocks_read_their_neighbours_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID], switch_on: None
) -> None:
    """장면 경계가 있는 화에서 두 장면에 걸친 요청은 차감 전 422 `NOVEL_BLOCKS_NOT_IN_ONE_SCENE` 이다. 수정으로 생긴 행 없는 블록은
    앞 블록의 장면, 화 맨 앞의 행 없는 블록은 뒤 첫 행 있는 블록의 장면으로 읽는다. 받은 요청은 그 장면 id 를 작업에 적는다.
    깨지는 시나리오: 다른 장면 문단까지 한 번에 고쳐 장면 경계를 넘는 수정안이 나오거나, 새로 나눈 문단을 장면 밖으로 읽어
    같은 장면 요청이 거절된다."""
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    ids = base.block_ids
    # 블록 0: 행 없음(맨 앞 → s1), 1: s1, 2: 행 없음(앞 → s1), 3: s2
    await _scene_rows(db_session, novel_id, chapter, {ids[1]: "s1", ids[3]: "s2"})
    url = _url(novel_id, chapter.id)

    across = await db_client.post(url, json=_request(base, [2, 3]))
    jobs_after_refusal = await _jobs(db_session, novel_id)
    within = await db_client.post(url, json=_request(base, [0, 1, 2]))

    assert _code(across) == (422, {"code": "NOVEL_BLOCKS_NOT_IN_ONE_SCENE"})
    assert jobs_after_refusal == []
    assert within.status_code == 202, within.text
    (job,) = await _jobs(db_session, novel_id)
    assert job.block_edit is not None and job.block_edit["sceneId"] == "s1"
    assert await _novel_ledger(db_session, user_id) == [("novelize_spend", -20)]


async def test_an_input_over_the_cap_is_422_before_charging_and_the_cap_itself_passes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID], switch_on: None
) -> None:
    """입력 견적(문맥 문단 + 작품 설정 + 설정 노트 + 지시)이 상한을 넘으면 차감 전 422 `NOVEL_EDIT_INPUT_TOO_LONG` +
    `estimatedInputChars`·`maxInputChars`, 견적이 상한과 같으면 받는다. 장면 있는 화는 그 장면 문단만 센다."""
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    url = _url(novel_id, chapter.id)
    monkeypatch.setattr(settings, "novelize_block_edit_max_input_chars", 10)

    over = await db_client.post(url, json=_request(base, [0]))
    estimate = over.json()["detail"]["estimatedInputChars"]
    monkeypatch.setattr(settings, "novelize_block_edit_max_input_chars", estimate - 1)
    just_over = await db_client.post(url, json=_request(base, [0]))
    jobs_before = await _jobs(db_session, novel_id)
    monkeypatch.setattr(settings, "novelize_block_edit_max_input_chars", estimate)
    at_cap = await db_client.post(url, json=_request(base, [0]))

    assert _code(over) == (
        422,
        {"code": "NOVEL_EDIT_INPUT_TOO_LONG", "estimatedInputChars": estimate, "maxInputChars": 10},
    )
    assert estimate >= sum(len(p) for p in split_paragraphs(_BODY)) + len("더 쓸쓸하게")
    assert just_over.status_code == 422
    assert jobs_before == []
    assert at_cap.status_code == 202, at_cap.text
    assert await _novel_ledger(db_session, user_id) == [("novelize_spend", -20)]


async def test_the_input_estimate_of_a_chapter_with_scenes_counts_only_the_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID], switch_on: None
) -> None:
    """장면 있는 화의 견적은 대상 장면 문단만 센다 — 모델에 가는 문맥이 그 장면뿐이라서다. 깨지는 시나리오: 긴 화의 짧은 장면
    하나를 고치는데 화 전체 길이로 거절된다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    url = _url(novel_id, chapter.id)
    monkeypatch.setattr(settings, "novelize_block_edit_max_input_chars", 10)
    whole = (await db_client.post(url, json=_request(base, [0]))).json()["detail"]["estimatedInputChars"]
    await _scene_rows(db_session, novel_id, chapter, {base.block_ids[0]: "s1", base.block_ids[1]: "s2"})

    scene = (await db_client.post(url, json=_request(base, [0]))).json()["detail"]["estimatedInputChars"]

    paragraphs = split_paragraphs(_BODY)
    assert whole - scene == sum(len(p) for p in paragraphs[1:])


async def test_a_restricted_work_refuses_a_block_edit_before_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enqueued: list[uuid.UUID], switch_on: None
) -> None:
    user_id, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    novel = await db_session.get_one(Novel, novel_id)
    await db_session.execute(
        sa.update(Content).where(Content.id == novel.content_id).values(moderation_status=ModerationStatus.RESTRICTED)
    )
    await db_session.commit()

    resp = await db_client.post(_url(novel_id, chapter.id), json=_request(base, [0]))

    assert resp.status_code == 403
    assert await _novel_ledger(db_session, user_id) == []


# ── 끝난 패치 작업과 옛 경로 ─────────────────────────────────────────────────
async def _patch_job(
    db: AsyncSession,
    novel_id: uuid.UUID,
    chapter: NovelChapter,
    base: NovelChapterRevision,
    positions: list[int],
    *,
    bundle: bool = False,
    **overrides: object,
) -> NovelJob:
    """`positions` 문단마다 "고친 n." 패치를 가진 끝난 패치 작업. `bundle` 이면 패치 전부를 한 묶음으로 둔다."""
    paragraphs = split_paragraphs(base.body)
    targets = request_targets([base.block_ids[i] for i in positions], base.block_ids, paragraphs)
    patches, bundles, _ = normalized_result(
        targets,
        [(i + 1, [f"고친 {i + 1}."]) for i in positions],
        [([i + 1 for i in positions], "앞이 정한 사실을 뒤가 쓴다")] if bundle else [],
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
        "block_edit": BlockEdit(targets=targets, scene_id=None, patches=patches, bundles=bundles).to_json(),
    }
    values.update(overrides)
    job = NovelJob(**values)
    db.add(job)
    await db.commit()
    return job


async def test_the_detail_lists_pending_patches_with_live_freshness_and_never_as_an_old_preview(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상세의 `pendingBlockEdits` 는 대기 패치가 있는 패치 작업마다 지시·패치(상태·블록 id·문단·지금 신선한가)·묶음을 싣는다.
    신선함은 지금 개정으로 계산한다 — 사용자가 고친 블록의 패치는 낡음으로 보인다(같은 작업의 다른 패치는 그대로 신선). 패치
    작업은 옛 `pendingAiEdits` 에 섞이지 않고, 버린 작업·실패 작업·대기 패치가 남지 않은 작업은 목록에 없다. 스위치와 무관하다(끈 뒤에도 남은 패치를 본다).
    깨지는 시나리오: 패치 하나를 고친 사용자 화면에서 같은 작업의 다른 패치까지 사라지거나, 옛 목록이 범위 없는 행에서 500 이 된다."""
    monkeypatch.setattr(settings, "novelize_multi_block_edit_enabled", False)
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [0, 1], bundle=True)
    await _patch_job(db_session, novel_id, chapter, base, [2], dismissed_at=sa.func.now(), instruction=None)
    await _patch_job(db_session, novel_id, chapter, base, [3], status="failed", charged_amount=0)
    finished = await _patch_job(db_session, novel_id, chapter, base, [2])
    assert finished.block_edit is not None
    finished.block_edit = {
        **finished.block_edit,
        "patches": [{**patch, "state": "applied", "paragraphs": None} for patch in finished.block_edit["patches"]],
    }
    # 사용자가 둘째 블록을 고친 새 개정이 커밋됐고 그 뒤 비우기는 아직 돌기 전인 틈 — 개정을 직접 넣는다(라우트는 곧바로 비운다).
    db_session.add(
        build_revision(
            body=_BODY.replace("둘째 문단이다.", "사용자가 고친 둘째."),
            source="manual_edit",
            block_ids=base.block_ids,
            chapter_id=chapter.id,
            revision_no=base.revision_no + 1,
        )
    )
    await db_session.commit()

    detail = (await db_client.get(f"/novels/{novel_id}")).json()

    assert detail["pendingAiEdits"] == []
    (listed,) = detail["pendingBlockEdits"]
    assert (listed["id"], listed["chapterId"], listed["instruction"]) == (str(job.id), str(chapter.id), "더 쓸쓸하게")
    assert [(p["blockId"], p["state"], p["paragraphs"], p["fresh"]) for p in listed["patches"]] == [
        (str(base.block_ids[0]), "pending", ["고친 1."], True),
        (str(base.block_ids[1]), "pending", ["고친 2."], False),
    ]
    assert [(b["patchIds"], b["reason"]) for b in listed["bundles"]] == [
        ([p["id"] for p in listed["patches"]], "앞이 정한 사실을 뒤가 쓴다")
    ]


async def test_old_apply_refuses_a_patch_job_and_old_dismiss_drops_all_its_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """옛 적용은 범위가 없는 패치 작업을 409 `NOVEL_JOB_NOT_APPLICABLE` 로 거절하고 아무것도 쓰지 않는다. 옛 버리기는 "전부 버리기"
    — 버린 시각을 찍고 지시문·패치 문단·묶음 이유를 비우며, 패치 상태(버림)와 블록 id 는 기록으로 남긴다. 깨지는 시나리오: 옛
    화면이 패치 작업을 버렸는데 사용자 글에서 나온 문단이 행에 남는다(처리방침의 즉시 삭제)."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [0, 1], bundle=True)

    applied = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/apply")
    revisions_after_apply = (await _current(db_session, chapter.id)).revision_no
    dismissed = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/dismiss")

    assert _code(applied) == (409, {"code": "NOVEL_JOB_NOT_APPLICABLE"})
    assert revisions_after_apply == 1
    assert dismissed.status_code == 204
    (stored,) = await _jobs(db_session, novel_id)
    assert stored.dismissed_at is not None and stored.instruction is None and stored.result_text is None
    assert stored.block_edit is not None
    assert [(p["blockId"], p["state"], p["paragraphs"]) for p in stored.block_edit["patches"]] == [
        (str(base.block_ids[0]), "dismissed", None),
        (str(base.block_ids[1]), "dismissed", None),
    ]
    assert [b["reason"] for b in stored.block_edit["bundles"]] == [None]
    assert (await db_client.get(f"/novels/{novel_id}")).json()["pendingBlockEdits"] == []


async def test_deleting_the_last_batch_empties_its_patch_jobs(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """마지막 묶음 삭제는 그 화를 가리키던 패치 작업의 칸을 통째로 비운다 — 지운 화의 본문에서 나온 패치 문단이 남지 않는다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    await _patch_job(db_session, novel_id, chapter, base, [0])

    resp = await db_client.delete(f"/novels/{novel_id}/batches/{chapter.batch_id}")

    assert resp.status_code == 204, resp.text
    (stored,) = await _jobs(db_session, novel_id)
    assert (stored.chapter_id, stored.instruction, stored.block_edit) == (None, None, None)
    # JSON `null` 이 아니라 SQL NULL 이다 — "칸 없음" 판정(`IS NULL`)과 CHECK 가 이 행을 패치 작업으로 보지 않는다.
    connection = await db_session.connection()
    assert await connection.scalar(sa.text("SELECT block_edit IS NULL FROM novel_jobs WHERE id = :id"), {"id": stored.id})


async def test_the_old_stale_preview_erase_leaves_a_patch_job_instruction_and_untouched_patches(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """화의 글이 바뀌어 낡은 미리보기 비우기가 돌아도 패치 작업의 지시문과 바뀌지 않은 블록의 패치는 그대로다 — 옛 비우기는 결과
    본문이 있는 작업만 보고, 패치는 블록 단위로 낡는다(고친 블록의 패치만 낡음). 깨지는 시나리오: 패치 작업에 결과 본문을 채우는
    순간, 패치 하나를 적용해 화 해시가 바뀌면 같은 작업의 남은 패치 지시문까지 지워진다."""
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [0, 2])
    assert job.block_edit is not None
    untouched = job.block_edit["patches"][1]

    edited = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions",
        json={"baseRevisionId": str(base.id), "body": _BODY.replace("첫 문단이다.", "사용자가 고친 첫 문단.")},
    )

    assert edited.status_code == 201
    (stored,) = await _jobs(db_session, novel_id)
    assert (stored.instruction, stored.result_text) == ("더 쓸쓸하게", None)
    assert stored.block_edit is not None
    assert [(p["state"], p["paragraphs"]) for p in stored.block_edit["patches"]] == [("stale", None), ("pending", ["고친 3."])]
    assert stored.block_edit["patches"][1] == untouched


async def test_polling_a_patch_job_reports_no_range_and_no_whole_body(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    base = await _current(db_session, chapter.id)
    job = await _patch_job(db_session, novel_id, chapter, base, [0])

    resp = await db_client.get(f"/novels/{novel_id}/jobs/{job.id}")

    assert resp.status_code == 200
    assert resp.json()["aiEdit"] == {
        "baseRevisionId": str(base.id),
        "paragraphStart": None,
        "paragraphEnd": None,
        "instruction": "더 쓸쓸하게",
        "resultText": None,
    }


# ── 구조 ─────────────────────────────────────────────────────────────────────
_SRC = Path(__file__).resolve().parents[1] / "src" / "api"


def _clears_text_without_patches(tree: ast.AST) -> list[int]:
    """`.values(..., result_text=None, ...)` 인데 `block_edit` 를 다루지 않는 호출의 줄 번호."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "values"):
            continue
        names = {keyword.arg: keyword.value for keyword in node.keywords}
        cleared = names.get("result_text")
        if isinstance(cleared, ast.Constant) and cleared.value is None and "block_edit" not in names:
            lines.append(node.lineno)
    return lines


def _hash_calls_outside(tree: ast.AST) -> list[int]:
    names = ("block_hash", "patch_is_fresh")
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in names)
            or (isinstance(node.func, ast.Attribute) and node.func.attr in names)
        )
    ]


def test_the_guards_see_what_they_look_for() -> None:
    """아래 두 구조 검사의 신호 — 잡아야 할 꼴을 실제로 잡고, 지켜진 꼴은 놓아준다."""
    assert _clears_text_without_patches(ast.parse("update(J).values(instruction=None, result_text=None)")) == [1]
    assert _clears_text_without_patches(ast.parse("update(J).values(result_text=None, block_edit=None)")) == []
    assert _hash_calls_outside(ast.parse("x = block_hash(p)\ny = m.patch_is_fresh(a, b, c)")) == [1, 2]


def test_every_write_that_clears_the_whole_body_also_handles_the_patches() -> None:
    """작업 행의 지시문·결과 본문을 비우는 쓰기(적용·버리기·마지막 묶음 삭제·낡은 미리보기 비우기)는 모두 패치 칸도 함께 다룬다 —
    한 곳이라도 빠지면 그 자리에서 사용자 글에서 나온 패치 문단이 행에 남는다. 환불은 전이 값 dict 로 쓰여 이 검사 밖이지만, 환불은
    진행 중 작업에만 걸리고 그때 패치 칸에는 대상(블록 id·해시)뿐이라 비울 글이 없다."""
    offenders = {
        str(path.relative_to(_SRC)): lines
        for path in sorted(_SRC.rglob("*.py"))
        if (lines := _clears_text_without_patches(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert offenders == {}


def test_only_the_block_edit_module_hashes_blocks_and_judges_patches() -> None:
    """블록 해시와 패치 신선함 판정은 `block_edits.py` 의 한 함수에만 있다(요청·저장·목록이 모두 그 함수를 부른다) — 자리마다 다른
    판정이면 저장은 됐는데 목록에서 낡아 보이거나, 목록에서 신선한데 적용은 막히는 패치가 생긴다."""
    callers = {
        str(path.relative_to(_SRC))
        for path in sorted(_SRC.rglob("*.py"))
        if _hash_calls_outside(ast.parse(path.read_text(encoding="utf-8")))
    }
    assert callers <= {"novelize/block_edits.py"}
