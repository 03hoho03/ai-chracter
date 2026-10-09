"""노벨 게시자 라우트 — 공개 상태 조회, 공개(처음 공개·다음 화·다시 공개), 공개 거두기, 텍스트 심사 배선.

텍스트 심사 LLM 은 `get_llm_client` 를 가짜로 바꿔 끼운다. 가짜는 받은 지시문·본문·호출 문맥을 적고, 미리 정한 판정을
돌려주거나 예외를 낸다. 소설은 `_novel_setup`(방의 소설 만들기 라우트)으로 만들고 화는 `_add_batch` 로 직접 넣는다 — 방의
원작은 소설 소유자가 만든 작품이라, 남의 원작이 필요한 시험은 원작의 작가 칸을 다른 회원으로 바꾼다."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import Content, ContentVisibility, ModerationStatus, Novel
from api.db.models.novel import (
    NovelChapter,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelPublication,
    NovelScreening,
)
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMPolicyViolationError, T
from api.novel_public import screening
from api.novel_public.screening import NovelScreenResult
from factories import (
    _add_batch,
    _clear_llm_override,
    _make_user,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)


class _ScreenLLM(LLMClient):
    """텍스트 심사 가짜. `results` 를 앞에서부터 하나씩 돌려주고(예외면 낸다), 비면 통과다. `during_call` 이 있으면 판정을
    돌려주기 전에 부른다 — 심사를 기다리는 동안 다른 요청이 소설을 바꾼 상황을 만든다."""

    def __init__(self, *results: NovelScreenResult | Exception) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, str, LLMCallContext]] = []
        self.during_call: Callable[[], Awaitable[None]] | None = None

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise AssertionError("텍스트 심사는 스트리밍 생성을 쓰지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("텍스트 심사는 지시문을 따로 보내는 구조화 호출을 쓴다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        assert response_schema is NovelScreenResult
        self.calls.append((system_instruction, prompt, usage))
        if self.during_call is not None:
            await self.during_call()
        result = self.results.pop(0) if self.results else NovelScreenResult(passed=True, flagged_parts=[], reason=None)
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, response_schema)
        return result


def _rejected(*parts: str) -> NovelScreenResult:
    return NovelScreenResult.model_validate({"passed": False, "flagged_parts": list(parts), "reason": "기준에 걸린다"})


@pytest.fixture
def llm() -> Iterator[_ScreenLLM]:
    fake = _ScreenLLM()
    _override_llm_client(fake)
    yield fake
    _clear_llm_override()


@pytest.fixture(autouse=True)
def _novel_public_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_public_enabled", True)


async def _novel_with_chapters(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, chapters: int = 2
) -> tuple[uuid.UUID, list[NovelChapter]]:
    """화 `chapters` 개짜리 묶음 하나가 있는 소설. 소개를 채워 둔다(처음 공개가 함께 얼리고 심사한다)."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=3)
    messages = await _room_messages(db_session, room.room_id)
    added = await _add_batch(db_session, novel_id, room, messages[0], messages[-1], episodes=chapters)
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(synopsis="두 사람의 첫 만남."))
    await db_session.commit()
    return novel_id, added


async def _source(db_session: AsyncSession, novel_id: uuid.UUID) -> Content:
    novel = await db_session.get_one(Novel, novel_id)
    return await db_session.get_one(Content, novel.content_id)


async def _hand_source_to_someone_else(db_session: AsyncSession, novel_id: uuid.UUID, permission: str) -> None:
    other = _make_user()
    db_session.add(other)
    await db_session.flush()
    source = await _source(db_session, novel_id)
    source.creator_user_id = other.id
    source.novel_permission = permission  # type: ignore[assignment]
    await db_session.commit()


async def _new_revision(db_session: AsyncSession, chapter: NovelChapter, body: str) -> NovelChapterRevision:
    latest = await db_session.scalar(
        sa.select(sa.func.max(NovelChapterRevision.revision_no)).where(NovelChapterRevision.chapter_id == chapter.id)
    )
    revision = NovelChapterRevision(chapter_id=chapter.id, revision_no=(latest or 0) + 1, body=body, source="manual_edit")
    db_session.add(revision)
    await db_session.commit()
    return revision


async def _publish(db_client: httpx.AsyncClient, novel_id: uuid.UUID, chapter: NovelChapter | None) -> httpx.Response:
    return await db_client.post(
        f"/novels/{novel_id}/publication", json={"chapterId": str(chapter.id) if chapter is not None else None}
    )


async def _count(db_session: AsyncSession, model: Any, novel_id: uuid.UUID) -> int:
    return (
        await db_session.scalar(sa.select(sa.func.count()).select_from(model).where(model.novel_id == novel_id))
    ) or 0


# ── 스위치 ──────────────────────────────────────────────────────────────────
async def test_switch_off_closes_status_and_publish_before_the_llm(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    monkeypatch.setattr(settings, "novel_public_enabled", False)

    status_resp = await db_client.get(f"/novels/{novel_id}/publication")
    publish_resp = await _publish(db_client, novel_id, chapters[0])

    assert (status_resp.status_code, status_resp.json()["detail"]["code"]) == (403, "NOVEL_PUBLIC_DISABLED")
    assert (publish_resp.status_code, publish_resp.json()["detail"]["code"]) == (403, "NOVEL_PUBLIC_DISABLED")
    assert llm.calls == []


# ── 처음 공개 ────────────────────────────────────────────────────────────────
async def test_first_publish_freezes_metadata_and_chapter_one_after_screening(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(title="비 오는 날"))
    await db_session.execute(
        sa.update(NovelChapter).where(NovelChapter.id == chapters[0].id).values(title="첫 화", author_note="고마워요")
    )
    await db_session.commit()

    resp = await _publish(db_client, novel_id, chapters[0])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["published"], body["visibility"], body["moderationStatus"]) == (True, "public", "normal")
    assert (body["publishedChapterCount"], body["chapterCount"]) == (1, 2)
    assert body["lastScreening"]["outcome"] == "passed"

    (system_instruction, prompt, usage) = llm.calls[0]
    assert usage.call_site == "novel_publish_screen"
    assert "=== novel_title: 소설 제목 ===\n비 오는 날" in prompt
    assert "=== synopsis: 소개 ===\n두 사람의 첫 만남." in prompt
    assert "=== chapter_title: 화 제목 ===\n첫 화" in prompt
    assert "=== author_note: 작가의 말 ===\n고마워요" in prompt
    assert "=== chapter_body: 본문 ===\n첫 문단이다." in prompt
    # 게시자가 쓴 글은 지시문 통로에 실리지 않는다.
    assert "첫 문단이다." not in system_instruction and "[판정 방법]" in system_instruction

    publication = await db_session.get_one(NovelPublication, novel_id, populate_existing=True)
    assert (publication.title, publication.synopsis) == ("비 오는 날", "두 사람의 첫 만남.")
    frozen = await db_session.get_one(NovelChapterPublication, chapters[0].id, populate_existing=True)
    first_revision = await db_session.scalar(
        sa.select(NovelChapterRevision.id).where(NovelChapterRevision.chapter_id == chapters[0].id)
    )
    assert (frozen.ordinal, frozen.revision_id, frozen.title, frozen.author_note, frozen.edition) == (
        1,
        first_revision,
        "첫 화",
        "고마워요",
        1,
    )


async def test_publish_must_start_at_chapter_one_and_continue_without_gaps(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch, chapters=3)

    skipped = await _publish(db_client, novel_id, chapters[1])
    metadata_only = await _publish(db_client, novel_id, None)
    first = await _publish(db_client, novel_id, chapters[0])
    gap = await _publish(db_client, novel_id, chapters[2])
    second = await _publish(db_client, novel_id, chapters[1])

    assert (skipped.status_code, skipped.json()["detail"]) == (
        409,
        {"code": "NOVEL_PUBLISH_NOT_CONTIGUOUS", "nextOrdinal": 1},
    )
    assert (metadata_only.status_code, metadata_only.json()["detail"]["nextOrdinal"]) == (409, 1)
    assert first.status_code == 200
    assert (gap.status_code, gap.json()["detail"]["nextOrdinal"]) == (409, 2)
    assert second.json()["publishedChapterCount"] == 2
    assert len(llm.calls) == 2


async def test_chapter_from_another_novel_is_not_found(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, _chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)

    resp = await db_client.post(f"/novels/{novel_id}/publication", json={"chapterId": str(uuid.uuid4())})

    assert (resp.status_code, resp.json()["detail"]["code"]) == (404, "NOVEL_CHAPTER_NOT_FOUND")


# ── 심사 실패 ────────────────────────────────────────────────────────────────
async def test_rejection_writes_no_publication_and_names_the_flagged_parts(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """심사에 걸리면 공개본을 하나도 쓰지 않는다. 모델이 이번에 싣지 않은 자리(제목이 없는 소설의 `novel_title`)를
    짚어도 버리고, 거부 기록과 오늘 남은 횟수가 남는다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    llm.results = [_rejected("chapter_body", "novel_title")]

    resp = await _publish(db_client, novel_id, chapters[0])

    assert resp.status_code == 400
    assert resp.json()["detail"] == {
        "code": "NOVEL_SCREENING_REJECTED",
        "chapterOrdinal": 1,
        "flaggedParts": ["chapter_body"],
    }
    assert await _count(db_session, NovelPublication, novel_id) == 0
    assert await _count(db_session, NovelChapterPublication, novel_id) == 0
    row = await db_session.scalar(sa.select(NovelScreening).where(NovelScreening.novel_id == novel_id))
    assert row is not None
    assert (row.outcome, row.flagged_parts, row.reason, row.chapter_ordinal) == (
        "rejected",
        ["chapter_body"],
        "기준에 걸린다",
        1,
    )
    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    assert status_body["published"] is False
    assert status_body["lastScreening"]["flaggedParts"] == ["chapter_body"]
    assert (status_body["screeningRejectionsLeft"], status_body["screeningRejectionLimit"]) == (2, 3)


async def test_safety_block_counts_as_rejection_of_every_screened_part(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    llm.results = [LLMPolicyViolationError("blocked")]

    resp = await _publish(db_client, novel_id, chapters[0])

    assert resp.status_code == 400
    assert resp.json()["detail"]["flaggedParts"] == ["synopsis", "chapter_body"]


async def test_screening_failure_publishes_nothing_and_does_not_use_a_retry(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    llm.results = [LLMClientError("timeout")]

    resp = await _publish(db_client, novel_id, chapters[0])

    assert (resp.status_code, resp.json()["detail"]) == (503, {"code": "NOVEL_SCREENING_UNAVAILABLE"})
    assert await _count(db_session, NovelPublication, novel_id) == 0
    assert await _count(db_session, NovelScreening, novel_id) == 0
    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    assert status_body["screeningRejectionsLeft"] == 3


async def test_daily_rejection_limit_stops_before_calling_the_llm(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """상한 2 에서 두 번 걸리면 세 번째는 심사를 부르지 않고 429 다. 한 번 걸린 뒤에는 아직 부른다(상한을 1 번째 거부에서
    닫는 오프바이원을 가른다)."""
    monkeypatch.setattr(screening, "NOVEL_SCREEN_DAILY_REJECTION_LIMIT", 2)
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    llm.results = [_rejected("chapter_body"), _rejected("chapter_body")]

    first = await _publish(db_client, novel_id, chapters[0])
    second = await _publish(db_client, novel_id, chapters[0])
    third = await _publish(db_client, novel_id, chapters[0])

    assert (first.status_code, second.status_code) == (400, 400)
    assert third.status_code == 429
    assert third.json()["detail"]["window"] == "novel_screen"
    assert len(llm.calls) == 2


async def test_hourly_call_limit_counts_passing_screens_too(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """통과만 거듭해도 시간당 호출 상한에 닿는다 — 하루 상한은 거부만 세므로 통과를 세는 것은 이 상한뿐이다. 바뀐 것이 없는
    다시 공개는 심사를 부르지 않아 세지 않는다(상한 2 에서 그 요청이 끼어도 두 번째 심사가 막히지 않는다)."""
    monkeypatch.setattr(screening, "NOVEL_SCREEN_HOURLY_CALL_LIMIT", 2)
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)

    first = await _publish(db_client, novel_id, chapters[0])
    unchanged = await _publish(db_client, novel_id, chapters[0])
    second = await _publish(db_client, novel_id, chapters[1])
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(synopsis="고친 소개."))
    await db_session.commit()
    third = await _publish(db_client, novel_id, None)

    assert (first.status_code, unchanged.status_code, second.status_code) == (200, 200, 200)
    assert third.status_code == 429
    assert third.json()["detail"]["window"] == "novel_screen"
    assert len(llm.calls) == 2


# ── 다시 공개 ────────────────────────────────────────────────────────────────
async def test_republish_screens_only_what_changed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200

    # 다음 화: 소설 제목·소개가 그대로면 화 글만 싣는다.
    assert (await _publish(db_client, novel_id, chapters[1])).status_code == 200
    assert "=== synopsis" not in llm.calls[1][1]

    # 공개한 1화를 고치면 상태가 알리고, 다시 공개하면 그 화만 심사해 새 개정을 얼린다.
    edited = await _new_revision(db_session, chapters[0], "고친 첫 문단이다.")
    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    assert (status_body["changedChapterOrdinals"], status_body["metadataChanged"]) == ([1], False)

    republished = await _publish(db_client, novel_id, chapters[0])

    assert republished.status_code == 200
    assert republished.json()["changedChapterOrdinals"] == []
    prompt = llm.calls[2][1]
    assert "고친 첫 문단이다." in prompt and "=== synopsis" not in prompt
    frozen = await db_session.get_one(NovelChapterPublication, chapters[0].id, populate_existing=True)
    assert (frozen.revision_id, frozen.edition) == (edited.id, 2)

    # 바뀐 것이 없으면 심사도 쓰기도 없다.
    unchanged = await _publish(db_client, novel_id, chapters[0])
    assert unchanged.status_code == 200
    assert len(llm.calls) == 3


async def test_reverting_to_the_published_body_needs_no_screening(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """되돌리기는 같은 본문의 새 개정을 만든다 — 공개본과 글자가 같으면 바뀐 화가 아니다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    published_body = await db_session.scalar(
        sa.select(NovelChapterRevision.body).where(NovelChapterRevision.chapter_id == chapters[0].id)
    )
    assert published_body is not None
    await _new_revision(db_session, chapters[0], published_body)

    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    resp = await _publish(db_client, novel_id, chapters[0])

    assert status_body["changedChapterOrdinals"] == []
    assert resp.status_code == 200
    assert len(llm.calls) == 1


async def test_metadata_republish_screens_title_and_synopsis_only(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(synopsis="고친 소개."))
    await db_session.commit()
    assert (await db_client.get(f"/novels/{novel_id}/publication")).json()["metadataChanged"] is True

    resp = await _publish(db_client, novel_id, None)

    assert resp.status_code == 200
    assert resp.json()["metadataChanged"] is False
    prompt = llm.calls[1][1]
    assert "=== synopsis: 소개 ===\n고친 소개." in prompt and "=== chapter_body" not in prompt
    publication = await db_session.get_one(NovelPublication, novel_id, populate_existing=True)
    assert publication.synopsis == "고친 소개."


async def test_edit_during_screening_conflicts_and_writes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """심사를 기다리는 동안 화를 고치면 심사한 글과 얼릴 글이 달라진다 — 409 이고 공개본을 쓰지 않는다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)

    async def edit() -> None:
        await _new_revision(db_session, chapters[0], "심사 중에 고친 본문.")

    llm.during_call = edit

    resp = await _publish(db_client, novel_id, chapters[0])

    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "NOVEL_PUBLISH_CONFLICT")
    assert await _count(db_session, NovelPublication, novel_id) == 0
    assert await _count(db_session, NovelScreening, novel_id) == 0


# ── 원작 판정 ────────────────────────────────────────────────────────────────
async def test_someone_elses_source_needs_public_novel_permission(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    await _hand_source_to_someone_else(db_session, novel_id, "private")

    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    denied = await _publish(db_client, novel_id, chapters[0])
    (await _source(db_session, novel_id)).novel_permission = "public"
    await db_session.commit()
    allowed = await _publish(db_client, novel_id, chapters[0])

    assert status_body["newPublishBlock"] == "source_permission"
    assert denied.status_code == 403
    assert denied.json()["detail"] == {"code": "NOVEL_SOURCE_NOT_PUBLISHABLE", "reason": "source_permission"}
    assert allowed.status_code == 200
    assert len(llm.calls) == 1


async def test_own_source_skips_permission_but_not_the_listing_condition(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """원작자 본인은 허락이 '나만 보는 소설'이어도 공개할 수 있다. 원작이 비공개면 본인도 새로 공개할 수 없다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    source = await _source(db_session, novel_id)
    assert source.novel_permission == "private"
    source.visibility = ContentVisibility.PRIVATE
    await db_session.commit()

    hidden = await _publish(db_client, novel_id, chapters[0])
    source.visibility = ContentVisibility.PUBLIC
    await db_session.commit()
    allowed = await _publish(db_client, novel_id, chapters[0])

    assert (hidden.status_code, hidden.json()["detail"]["reason"]) == (409, "source_not_listed")
    assert allowed.status_code == 200


async def test_after_permission_downgrade_published_chapters_can_be_republished_but_not_extended(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    await _hand_source_to_someone_else(db_session, novel_id, "public")
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    source = await _source(db_session, novel_id)
    source.novel_permission = "private"
    source.visibility = ContentVisibility.PRIVATE
    await db_session.commit()
    await _new_revision(db_session, chapters[0], "고친 첫 문단이다.")

    next_chapter = await _publish(db_client, novel_id, chapters[1])
    republished = await _publish(db_client, novel_id, chapters[0])

    assert (next_chapter.status_code, next_chapter.json()["detail"]["reason"]) == (403, "source_permission")
    assert republished.status_code == 200
    assert republished.json()["republishBlock"] is None


async def test_restricted_source_blocks_republishing_too(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    (await _source(db_session, novel_id)).moderation_status = ModerationStatus.RESTRICTED
    await db_session.commit()
    await _new_revision(db_session, chapters[0], "고친 첫 문단이다.")

    resp = await _publish(db_client, novel_id, chapters[0])
    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()

    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "NOVEL_SOURCE_UNAVAILABLE")
    assert (status_body["republishBlock"], status_body["newPublishBlock"]) == (
        "source_unavailable",
        "source_unavailable",
    )
    assert len(llm.calls) == 1


async def test_operator_restricted_publication_cannot_be_republished(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    await db_session.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == novel_id).values(moderation_status="restricted")
    )
    await db_session.commit()

    resp = await _publish(db_client, novel_id, chapters[1])
    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()

    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "NOVEL_PUBLICATION_RESTRICTED")
    assert (status_body["moderationStatus"], status_body["republishBlock"]) == ("restricted", "restricted")


# ── 거두기 ──────────────────────────────────────────────────────────────────
async def test_withdraw_keeps_the_frozen_copies_and_republish_reopens_without_screening(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200

    withdrawn = await db_client.post(f"/novels/{novel_id}/publication/withdraw")
    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    reopened = await _publish(db_client, novel_id, None)

    assert withdrawn.status_code == 204
    assert (status_body["visibility"], status_body["publishedChapterCount"]) == ("withdrawn", 1)
    assert (reopened.status_code, reopened.json()["visibility"]) == (200, "public")
    assert len(llm.calls) == 1


async def test_withdraw_works_with_the_switch_off_and_novelize_access_revoked(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    monkeypatch.setattr(settings, "novel_public_enabled", False)
    monkeypatch.setattr(settings, "novelize_enabled", False)

    resp = await db_client.post(f"/novels/{novel_id}/publication/withdraw")

    assert resp.status_code == 204
    publication = await db_session.get_one(NovelPublication, novel_id, populate_existing=True)
    assert publication.visibility == "withdrawn"


async def test_withdraw_needs_a_publication_and_ownership(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, _chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    never = await db_client.post(f"/novels/{novel_id}/publication/withdraw")
    stranger = Novel(
        user_id=(await _make_stranger(db_session)).id,
        content_id=uuid.uuid4(),
        content_type="character",
        content_title="남의 원작",
    )
    db_session.add(stranger)
    await db_session.commit()

    foreign = await db_client.post(f"/novels/{stranger.id}/publication/withdraw")

    assert (never.status_code, never.json()["detail"]["code"]) == (404, "NOVEL_PUBLICATION_NOT_FOUND")
    assert (foreign.status_code, foreign.json()["detail"]["code"]) == (403, "NOVEL_FORBIDDEN")


async def _make_stranger(db_session: AsyncSession) -> Any:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    return user


# ── 삭제 ────────────────────────────────────────────────────────────────────
async def test_deleting_the_last_batch_drops_its_published_chapters(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """마지막 묶음을 지우면 그 묶음의 공개 화가 빠지고 앞 묶음의 공개 화는 1화부터 이어진 채 남는다. 공개를 이어 가면
    다음 번호는 남은 공개 화 수 + 1 이다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=3)
    messages = await _room_messages(db_session, room.room_id)
    (first,) = await _add_batch(db_session, novel_id, room, messages[0], messages[2])
    (second,) = await _add_batch(db_session, novel_id, room, messages[3], messages[-1])
    assert (await _publish(db_client, novel_id, first)).status_code == 200
    assert (await _publish(db_client, novel_id, second)).status_code == 200

    deleted = await db_client.delete(f"/novels/{novel_id}/batches/{second.batch_id}")
    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()

    assert deleted.status_code == 204
    assert (status_body["published"], status_body["publishedChapterCount"]) == (True, 1)
