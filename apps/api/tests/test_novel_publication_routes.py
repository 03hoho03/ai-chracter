"""노벨 게시자 라우트 — 공개 상태 조회, 공개(처음 공개·다음 화·다시 공개), 공개 거두기, 텍스트 심사 배선. 뒤쪽은 정책
스위치(`novel_public_policy_v2_enabled`)가 켜졌을 때의 첫 공개 운영자 승인·반려와, 스위치와 무관하게 첫 공개 때 찍히는
연재권 잠금이다.

텍스트 심사 LLM 은 `get_llm_client` 를 가짜로 바꿔 끼운다. 가짜는 받은 지시문·본문·호출 문맥을 적고, 미리 정한 판정을
돌려주거나 예외를 낸다. 소설은 `_novel_setup`(방의 소설 만들기 라우트)으로 만들고 화는 `_add_batch` 로 직접 넣는다 — 방의
원작은 소설 소유자가 만든 작품이라, 남의 원작이 필요한 시험은 원작의 작가 칸을 다른 회원으로 바꾼다."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import Settings, settings
from api.db.models import AdminActionLog, Content, ContentVisibility, ModerationStatus, Novel
from api.db.models.novel import (
    NovelChapter,
    NovelChapterEdition,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelPublication,
    NovelPurchase,
    NovelScreening,
)
from api.legal.documents import current_legal_version
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMPolicyViolationError, T
from api.novel_public import screening
from api.novel_public.screening import NovelScreenResult
from factories import (
    _add_batch,
    _clear_llm_override,
    _create_admin,
    _login_as,
    _login_as_admin,
    _make_user,
    _make_user_with_clover_lot,
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


async def test_preview_list_closes_status_and_publish_to_a_publisher_outside_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """미리보기 명단이 있으면 명단 밖 게시자는 스위치가 꺼진 것과 같은 403 을 받고, 명단의 게시자는 그대로 공개한다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    publisher = (await db_session.get_one(Novel, novel_id)).user_id

    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [uuid.uuid4()])
    status_resp = await db_client.get(f"/novels/{novel_id}/publication")
    blocked = await _publish(db_client, novel_id, chapters[0])
    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [publisher])
    allowed = await _publish(db_client, novel_id, chapters[0])

    assert (status_resp.status_code, status_resp.json()["detail"]["code"]) == (403, "NOVEL_PUBLIC_DISABLED")
    assert (blocked.status_code, blocked.json()["detail"]["code"]) == (403, "NOVEL_PUBLIC_DISABLED")
    assert allowed.status_code == 200
    assert len(llm.calls) == 1


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
    assert third.json()["detail"]["window"] == "novel_screen_daily_reject"
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
    assert third.json()["detail"]["window"] == "novel_screen_hourly"
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
    """원작자 본인은 허락이 '허용 안 함'이어도 공개할 수 있다(허락은 남에게 거는 조건이다). 원작이 비공개면 본인도 새로
    공개할 수 없다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    source = await _source(db_session, novel_id)
    source.novel_permission = "forbidden"
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


# ── 정책 스위치 공통 ─────────────────────────────────────────────────────────
def _policy(monkeypatch: pytest.MonkeyPatch, *, on: bool) -> None:
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", on)


async def _publication_row(db_session: AsyncSession, novel_id: uuid.UUID) -> NovelPublication | None:
    return await db_session.get(NovelPublication, novel_id, populate_existing=True)


async def _novel_row(db_session: AsyncSession, novel_id: uuid.UUID) -> Novel:
    return await db_session.get_one(Novel, novel_id, populate_existing=True)


async def _lock_copy(db_session: AsyncSession, novel_id: uuid.UUID) -> tuple[object, ...]:
    novel = await _novel_row(db_session, novel_id)
    return (
        novel.serial_locked_at,
        novel.serial_lock_source,
        novel.serial_lock_permission,
        novel.serial_lock_content_version_id,
        novel.serial_lock_terms_version,
    )


async def _assert_locked_at_first_publish(db_session: AsyncSession, novel_id: uuid.UUID) -> None:
    """연재권 잠금이 첫 공개로 찍혔고, 잠글 때의 원작 허락·원작 게시본·시행 중인 약관 판을 사본으로 들었다."""
    novel = await _novel_row(db_session, novel_id)
    source = await db_session.get_one(Content, novel.content_id, populate_existing=True)
    assert source.current_published_version_id is not None
    terms = await current_legal_version(db_session, "terms", now=datetime.now(UTC))
    assert novel.serial_locked_at is not None
    assert (
        novel.serial_lock_source,
        novel.serial_lock_permission,
        novel.serial_lock_content_version_id,
        novel.serial_lock_terms_version,
    ) == ("first_publish", source.novel_permission, source.current_published_version_id, terms)


async def _pending(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_permission: str | None = None,
) -> tuple[uuid.UUID, list[NovelChapter]]:
    """정책 스위치를 켜고 1화를 공개 신청해 운영자 승인을 기다리게 둔 소설(2화짜리). `source_permission` 을 주면 신청 전에
    원작을 그 허락 값의 다른 회원 작품으로 바꾼다."""
    _policy(monkeypatch, on=True)
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    if source_permission is not None:
        await _hand_source_to_someone_else(db_session, novel_id, source_permission)
    resp = await _publish(db_client, novel_id, chapters[0])
    assert resp.status_code == 200, resp.text
    return novel_id, chapters


async def _as_admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> uuid.UUID:
    """운영자 세션을 같은 클라이언트에 싣는다(회원 세션과 쿠키 이름이 달라 게시자 세션은 그대로 남는다)."""
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin)
    admin_id = admin["id"]
    assert isinstance(admin_id, uuid.UUID)
    return admin_id


async def _review(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, action: str, comment: str = "운영자가 확인했다"
) -> httpx.Response:
    return await db_client.post(f"/admin/novels/{novel_id}/review", json={"action": action, "adminComment": comment})


async def _review_logs(db_session: AsyncSession) -> list[tuple[str, uuid.UUID | None, uuid.UUID | None, str]]:
    rows = await db_session.execute(
        sa.select(
            AdminActionLog.action_type,
            AdminActionLog.target_user_id,
            AdminActionLog.target_novel_id,
            AdminActionLog.reason_text,
        ).where(AdminActionLog.action_type.in_(["novel-review-approve", "novel-review-reject"]))
    )
    return [(row[0], row[1], row[2], row[3]) for row in rows]


async def _reader_view(
    db_client: httpx.AsyncClient, db_session: AsyncSession, novel_id: uuid.UUID, chapter: NovelChapter
) -> tuple[bool, int, int, int]:
    """다른 회원으로 들어가 본 노벨 — 목록에 있는가, 작품 정보·1화 읽기·좋아요의 상태 코드. 끝나면 게시자 세션으로 돌린다."""
    owner = (await _novel_row(db_session, novel_id)).user_id
    reader = await _make_user_with_clover_lot(db_session, clover_balance=100)
    await db_session.commit()
    await _login_as(db_client, reader.id)
    listed = [item["id"] for item in (await db_client.get("/webnovels")).json()["items"]]
    detail = await db_client.get(f"/webnovels/{novel_id}")
    chapter_resp = await db_client.get(f"/webnovels/{novel_id}/chapters/{chapter.id}")
    like = await db_client.post(f"/webnovels/{novel_id}/like")
    await _login_as(db_client, owner)
    return str(novel_id) in listed, detail.status_code, chapter_resp.status_code, like.status_code


def test_policy_switch_is_off_unless_configured() -> None:
    """env 없이 배포하면 지금 약관 동작으로 뜬다 — 승인 대기는 개정 약관이 시행된 뒤 운영자가 켤 때만 생긴다."""
    assert Settings.model_fields["novel_public_policy_v2_enabled"].default is False


# ── 정책 스위치 꺼짐 — 지금 동작 그대로, 잠금 기록만 생긴다 ──────────────────────
async def test_switch_off_first_publish_opens_at_once_and_records_the_serial_lock(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """정책 스위치가 꺼져 있으면 첫 공개는 지금처럼 자동 글 심사를 통과하는 즉시 독자에게 열리고 심사 칸은 비어 있다. 연재권
    잠금은 스위치와 무관하게 이 첫 공개 순간에 찍힌다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    before = (await db_client.get(f"/novels/{novel_id}/publication")).json()

    resp = await _publish(db_client, novel_id, chapters[0])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert before["reviewRequired"] is False
    assert (body["visibility"], body["reviewStatus"], body["reviewReason"], body["reviewRequired"]) == (
        "public",
        None,
        None,
        False,
    )
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.visibility, publication.review_status, publication.reviewed_at) == ("public", None, None)
    await _assert_locked_at_first_publish(db_session, novel_id)


async def test_switch_off_a_locked_novel_still_needs_permission_for_the_next_chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """꺼져 있는 동안 잠금은 기록일 뿐이다 — 원작자가 소설화 허락을 거두면 잠긴 소설도 지금처럼 다음 화를 낼 수 없다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    await _hand_source_to_someone_else(db_session, novel_id, "public")
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    (await _source(db_session, novel_id)).novel_permission = "private"
    await db_session.commit()

    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    resp = await _publish(db_client, novel_id, chapters[1])

    assert (await _novel_row(db_session, novel_id)).serial_locked_at is not None
    assert status_body["newPublishBlock"] == "source_permission"
    assert (resp.status_code, resp.json()["detail"]) == (
        403,
        {"code": "NOVEL_SOURCE_NOT_PUBLISHABLE", "reason": "source_permission"},
    )


async def test_switch_off_later_publishes_keep_the_first_serial_lock(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """잠금은 한 번 찍히면 바뀌지 않는다 — 다음 화 공개, 고친 화 다시 공개, 거뒀다 다시 열기 모두 처음 값을 그대로 둔다.
    잠금 시각을 하루 앞으로 옮기고 원작 허락을 바꿔 두어, 다시 쓰면 값이 달라지게 한다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    await db_session.execute(
        sa.update(Novel)
        .where(Novel.id == novel_id)
        .values(serial_locked_at=sa.func.now() - sa.text("interval '1 day'"))
    )
    await db_session.commit()
    locked = await _lock_copy(db_session, novel_id)
    (await _source(db_session, novel_id)).novel_permission = "public"
    await db_session.commit()
    assert locked[2] != "public"

    next_chapter = await _publish(db_client, novel_id, chapters[1])
    await _new_revision(db_session, chapters[0], "고친 첫 문단이다.")
    republished = await _publish(db_client, novel_id, chapters[0])
    withdrawn = await db_client.post(f"/novels/{novel_id}/publication/withdraw")
    reopened = await _publish(db_client, novel_id, None)

    assert (next_chapter.status_code, republished.status_code, withdrawn.status_code, reopened.status_code) == (
        200,
        200,
        204,
        200,
    )
    assert await _lock_copy(db_session, novel_id) == locked


async def test_switch_off_a_leftover_pending_request_opens_at_once_and_clears_the_review(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """켜져 있을 때 들어간 승인 대기가 스위치를 끈 뒤에도 남아 있으면, 게시자의 다시 신청은 지금 동작대로 바로 공개되고
    심사 칸이 비워지며 그 순간 잠긴다. 승인처럼 그 순간이 처음 공개 시각이 된다(신청 시각을 하루 앞으로 옮겨 두어 다시
    썼는지 가린다)."""
    novel_id, chapters = await _pending(db_client, db_session, monkeypatch)
    await db_session.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == novel_id)
        .values(
            first_published_at=sa.func.now() - sa.text("interval '1 day'"),
            published_at=sa.func.now() - sa.text("interval '1 day'"),
        )
    )
    await db_session.commit()
    requested = await _publication_row(db_session, novel_id)
    assert requested is not None
    requested_at = requested.first_published_at
    _policy(monkeypatch, on=False)

    resp = await _publish(db_client, novel_id, chapters[0])

    assert resp.status_code == 200, resp.text
    assert (resp.json()["visibility"], resp.json()["reviewStatus"]) == ("public", None)
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.visibility, publication.review_status) == ("public", None)
    assert (publication.first_published_at > requested_at, publication.published_at > requested_at) == (True, True)
    await _assert_locked_at_first_publish(db_session, novel_id)
    listed, detail_status, _chapter_status, _like_status = await _reader_view(
        db_client, db_session, novel_id, chapters[0]
    )
    assert (listed, detail_status) == (True, 200)


async def test_switch_off_a_leftover_pending_request_still_needs_the_current_permission(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """대기 중인 공개는 독자에게 보인 적이 없으므로 처음 공개와 같이 지금 허락을 본다 — 대기 중에 원작자가 허락을 거뒀으면
    1화를 다시 내든 화 없이 다시 열든 403 이고, 허락 검사를 거치지 않은 잠금이 생기지 않는다."""
    novel_id, chapters = await _pending(db_client, db_session, monkeypatch, source_permission="public")
    (await _source(db_session, novel_id)).novel_permission = "private"
    await db_session.commit()
    _policy(monkeypatch, on=False)

    same_chapter = await _publish(db_client, novel_id, chapters[0])
    metadata_only = await _publish(db_client, novel_id, None)

    refused = {"code": "NOVEL_SOURCE_NOT_PUBLISHABLE", "reason": "source_permission"}
    assert (same_chapter.status_code, same_chapter.json()["detail"]) == (403, refused)
    assert (metadata_only.status_code, metadata_only.json()["detail"]) == (403, refused)
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.visibility, publication.review_status) == ("withdrawn", "pending")
    assert (await _novel_row(db_session, novel_id)).serial_locked_at is None


# ── 정책 스위치 켜짐 — 첫 공개 승인 대기 ─────────────────────────────────────────
async def test_first_publish_waits_for_operator_review_even_on_the_publishers_own_source(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """스위치가 켜지면 아직 독자에게 보인 적 없는 소설의 첫 공개는 자동 글 심사를 통과한 뒤 운영자 승인을 기다린다. 공개
    범위는 거둠과 같은 `withdrawn` 이라 심사 칸을 모르는 판정도 독자에게 내보내지 않는다. 원작이 게시자 자신의 작품이어도
    같다 — 승인은 원작 허락이 아니라 첫 공개 글을 본다. 잠금은 승인 때 찍히므로 아직 없다."""
    _policy(monkeypatch, on=True)
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    novel = await _novel_row(db_session, novel_id)
    assert (await _source(db_session, novel_id)).creator_user_id == novel.user_id
    before = (await db_client.get(f"/novels/{novel_id}/publication")).json()

    resp = await _publish(db_client, novel_id, chapters[0])

    assert before["reviewRequired"] is True
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["published"], body["visibility"], body["reviewStatus"], body["reviewReason"]) == (
        True,
        "withdrawn",
        "pending",
        None,
    )
    assert body["publishedChapterCount"] == 1
    assert len(llm.calls) == 1
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.visibility, publication.review_status) == ("withdrawn", "pending")
    assert (await _novel_row(db_session, novel_id)).serial_locked_at is None


async def test_a_pending_novel_is_hidden_from_every_reader_route(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _pending(db_client, db_session, monkeypatch)

    assert await _reader_view(db_client, db_session, novel_id, chapters[0]) == (False, 404, 404, 404)


async def test_publish_requests_during_review_are_refused_before_screening(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """대기 중에는 다음 화·고친 1화·제목과 소개 다시 공개를 모두 409 로 막는다 — 운영자가 본 글과 승인되는 글이 같게.
    다시 시도해도 풀리지 않으므로 그사이 바뀜(`NOVEL_PUBLISH_CONFLICT`)과 다른 코드이고, 심사를 부르지 않는다."""
    novel_id, chapters = await _pending(db_client, db_session, monkeypatch)

    next_chapter = await _publish(db_client, novel_id, chapters[1])
    await _new_revision(db_session, chapters[0], "고친 첫 문단이다.")
    same_chapter = await _publish(db_client, novel_id, chapters[0])
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(synopsis="고친 소개."))
    await db_session.commit()
    metadata_only = await _publish(db_client, novel_id, None)

    for resp in (next_chapter, same_chapter, metadata_only):
        assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "NOVEL_PUBLICATION_IN_REVIEW")
    assert len(llm.calls) == 1
    assert await _count(db_session, NovelChapterPublication, novel_id) == 1
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.review_status, publication.synopsis) == ("pending", "두 사람의 첫 만남.")


async def test_withdrawing_during_review_cancels_the_request_and_a_new_one_waits_again(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """대기 중 거두기는 신청 취소다 — 독자에게 보인 적 없는 글이라 공개 상태 행과 화 공개본을 남기지 않는다. 다시 신청하면
    처음 공개처럼 심사를 거쳐 새로 대기한다."""
    novel_id, chapters = await _pending(db_client, db_session, monkeypatch)

    cancelled = await db_client.post(f"/novels/{novel_id}/publication/withdraw")
    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    again = await _publish(db_client, novel_id, chapters[0])

    assert cancelled.status_code == 204
    assert (status_body["published"], status_body["publishedChapterCount"]) == (False, 0)
    assert (again.status_code, again.json()["reviewStatus"]) == (200, "pending")
    assert len(llm.calls) == 2
    assert (await _novel_row(db_session, novel_id)).serial_locked_at is None


async def test_withdrawing_an_approved_publication_keeps_the_frozen_copies(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """승인된 공개를 거두는 것은 신청 취소가 아니라 지금의 거두기다 — 공개 상태 행과 화 공개본이 남고 다시 열 수 있다."""
    novel_id, _chapters = await _pending(db_client, db_session, monkeypatch)
    await _as_admin(db_client, db_session)
    assert (await _review(db_client, novel_id, "approve")).status_code == 200

    withdrawn = await db_client.post(f"/novels/{novel_id}/publication/withdraw")

    assert withdrawn.status_code == 204
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.visibility, publication.review_status) == ("withdrawn", "approved")
    assert await _count(db_session, NovelChapterPublication, novel_id) == 1


async def test_operator_approval_opens_the_novel_and_records_the_serial_lock(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """승인하면 독자에게 열리고 그 순간이 처음 공개 시각이 된다(신청 시각을 하루 앞으로 옮겨 두어 다시 썼는지 가린다).
    연재권 잠금이 승인 때 찍히고, 조치가 게시자·노벨을 대상으로 감사 로그에 남는다."""
    novel_id, chapters = await _pending(db_client, db_session, monkeypatch)
    await db_session.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == novel_id)
        .values(
            first_published_at=sa.func.now() - sa.text("interval '1 day'"),
            published_at=sa.func.now() - sa.text("interval '1 day'"),
        )
    )
    await db_session.commit()
    requested = await _publication_row(db_session, novel_id)
    assert requested is not None
    requested_at = requested.first_published_at
    await _as_admin(db_client, db_session)

    resp = await _review(db_client, novel_id, "approve")

    assert resp.status_code == 200, resp.text
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.visibility, publication.review_status, publication.review_reason) == ("public", "approved", None)
    assert publication.reviewed_at is not None
    assert publication.first_published_at > requested_at
    assert publication.published_at > requested_at
    await _assert_locked_at_first_publish(db_session, novel_id)
    owner = (await _novel_row(db_session, novel_id)).user_id
    assert await _review_logs(db_session) == [("novel-review-approve", owner, novel_id, "운영자가 확인했다")]
    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    assert (status_body["visibility"], status_body["reviewStatus"], status_body["reviewRequired"]) == (
        "public",
        "approved",
        False,
    )
    listed, detail_status, chapter_status, _like_status = await _reader_view(
        db_client, db_session, novel_id, chapters[0]
    )
    assert (listed, detail_status, chapter_status) == (True, 200, 200)


async def test_operator_rejection_needs_a_reason_and_hands_it_to_the_publisher_as_written(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """반려 사유는 운영자가 쓴 글 그대로 게시자 공개 상태에 실린다(공백뿐이면 422). 반려하면 화 공개본이 지워지고 공개
    상태 행은 사유를 들고 남는다. 독자에게는 계속 없다."""
    novel_id, chapters = await _pending(db_client, db_session, monkeypatch)
    await _as_admin(db_client, db_session)
    reason = "1화 끝 장면의 묘사가 운영정책에 맞지 않아요. 고쳐서 다시 신청해 주세요."

    blank = await _review(db_client, novel_id, "reject", "   ")
    resp = await _review(db_client, novel_id, "reject", reason)

    assert blank.status_code == 422
    assert resp.status_code == 200, resp.text
    assert await _count(db_session, NovelChapterPublication, novel_id) == 0
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.visibility, publication.review_status, publication.review_reason) == (
        "withdrawn",
        "rejected",
        reason,
    )
    assert publication.reviewed_at is not None
    assert (await _novel_row(db_session, novel_id)).serial_locked_at is None
    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    assert (status_body["reviewStatus"], status_body["reviewReason"], status_body["publishedChapterCount"]) == (
        "rejected",
        reason,
        0,
    )
    owner = (await _novel_row(db_session, novel_id)).user_id
    assert await _review_logs(db_session) == [("novel-review-reject", owner, novel_id, reason)]
    _listed, detail_status, _chapter_status, _like_status = await _reader_view(
        db_client, db_session, novel_id, chapters[0]
    )
    assert detail_status == 404


async def test_republishing_after_rejection_screens_again_and_waits_with_the_reason_cleared(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _pending(db_client, db_session, monkeypatch)
    await _as_admin(db_client, db_session)
    assert (await _review(db_client, novel_id, "reject", "다시 써 주세요.")).status_code == 200

    resp = await _publish(db_client, novel_id, chapters[0])

    assert resp.status_code == 200, resp.text
    assert (resp.json()["reviewStatus"], resp.json()["reviewReason"], resp.json()["visibility"]) == (
        "pending",
        None,
        "withdrawn",
    )
    assert len(llm.calls) == 2
    assert await _count(db_session, NovelChapterPublication, novel_id) == 1
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.review_status, publication.review_reason) == ("pending", None)


async def test_a_rejected_request_cannot_be_reopened_without_chapter_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """반려된 공개는 화 공개본이 없다 — 화 없이 다시 열기는 처음 공개와 같이 1화부터 내라는 409 이고 대기를 만들지 않는다."""
    novel_id, _chapters = await _pending(db_client, db_session, monkeypatch)
    await _as_admin(db_client, db_session)
    assert (await _review(db_client, novel_id, "reject", "다시 써 주세요.")).status_code == 200

    resp = await _publish(db_client, novel_id, None)

    assert (resp.status_code, resp.json()["detail"]) == (409, {"code": "NOVEL_PUBLISH_NOT_CONTIGUOUS", "nextOrdinal": 1})
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.visibility, publication.review_status) == ("withdrawn", "rejected")
    assert len(llm.calls) == 1


async def test_after_approval_the_next_chapter_opens_without_review(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _pending(db_client, db_session, monkeypatch)
    await _as_admin(db_client, db_session)
    assert (await _review(db_client, novel_id, "approve")).status_code == 200

    resp = await _publish(db_client, novel_id, chapters[1])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["visibility"], body["publishedChapterCount"], body["reviewStatus"], body["reviewRequired"]) == (
        "public",
        2,
        "approved",
        False,
    )


async def test_review_needs_a_pending_request(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """공개 상태 행이 없으면 404, 대기가 아닌 행(이미 승인됨, 심사 없이 공개됨)의 승인·반려는 409 다 — 감사 로그에 빈 조치가
    쌓이지 않게."""
    published_id, published_chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    assert (await _publish(db_client, published_id, published_chapters[0])).status_code == 200
    _policy(monkeypatch, on=True)
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    await _as_admin(db_client, db_session)

    never = await _review(db_client, novel_id, "approve")
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    approved = await _review(db_client, novel_id, "approve")
    approve_again = await _review(db_client, novel_id, "approve")
    reject_approved = await _review(db_client, novel_id, "reject", "늦은 반려")
    unreviewed = await _review(db_client, published_id, "approve")

    assert (never.status_code, never.json()["detail"]["code"]) == (404, "NOVEL_NOT_FOUND")
    assert approved.status_code == 200
    for resp in (approve_again, reject_approved, unreviewed):
        assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "NOVEL_REVIEW_NOT_PENDING")
    assert [log[0] for log in await _review_logs(db_session)] == ["novel-review-approve"]


async def test_approval_rechecks_the_source_permission_and_changes_nothing_when_it_was_withdrawn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """잠기기 전이라 승인 순간의 원작 허락을 다시 본다. 대기 중에 원작자가 허락을 거뒀으면 승인은 409 이고 공개 범위·잠금·
    감사 로그 모두 그대로다(운영자는 반려로 처리한다)."""
    novel_id, _chapters = await _pending(db_client, db_session, monkeypatch, source_permission="public")
    (await _source(db_session, novel_id)).novel_permission = "private"
    await db_session.commit()
    await _as_admin(db_client, db_session)

    resp = await _review(db_client, novel_id, "approve")

    assert (resp.status_code, resp.json()["detail"]) == (
        409,
        {"code": "NOVEL_SOURCE_NOT_PUBLISHABLE", "reason": "source_permission"},
    )
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.visibility, publication.review_status) == ("withdrawn", "pending")
    assert (await _novel_row(db_session, novel_id)).serial_locked_at is None
    assert await _review_logs(db_session) == []


async def test_approval_needs_chapter_one_still_published(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """대기 중에 1화가 든 마지막 묶음을 지우면 공개 상태 행은 남고 화 공개본만 사라진다. 그 승인은 공개 화가 하나도 없는
    소설에 잠금을 주게 되므로 409 이고(이미 처리됨과 다른 코드 — 운영자가 반려해야 한다는 신호), 아무것도 바뀌지 않는다."""
    novel_id, chapters = await _pending(db_client, db_session, monkeypatch)
    deleted = await db_client.delete(f"/novels/{novel_id}/batches/{chapters[0].batch_id}")
    assert deleted.status_code == 204
    assert await _count(db_session, NovelChapterPublication, novel_id) == 0
    await _as_admin(db_client, db_session)

    resp = await _review(db_client, novel_id, "approve")

    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "NOVEL_REVIEW_NO_FIRST_CHAPTER")
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.visibility, publication.review_status) == ("withdrawn", "pending")
    assert (await _novel_row(db_session, novel_id)).serial_locked_at is None


async def test_operator_can_still_review_after_the_switch_is_turned_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, _chapters = await _pending(db_client, db_session, monkeypatch)
    _policy(monkeypatch, on=False)
    await _as_admin(db_client, db_session)

    resp = await _review(db_client, novel_id, "approve")

    assert resp.status_code == 200, resp.text
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert (publication.visibility, publication.review_status) == ("public", "approved")
    await _assert_locked_at_first_publish(db_session, novel_id)


async def test_review_route_needs_an_operator(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """게시자 자신을 포함해 회원 세션으로는 승인할 수 없다."""
    novel_id, _chapters = await _pending(db_client, db_session, monkeypatch)

    as_member = await _review(db_client, novel_id, "approve")
    db_client.cookies.clear()
    anonymous = await _review(db_client, novel_id, "approve")

    assert (as_member.status_code, anonymous.status_code) == (401, 401)
    publication = await _publication_row(db_session, novel_id)
    assert publication is not None
    assert publication.review_status == "pending"


# ── 정책 스위치 켜짐 — 연재권 잠금 ───────────────────────────────────────────────
async def _locked_on_someone_elses_source(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[uuid.UUID, list[NovelChapter]]:
    """다른 회원의 원작(허락 public)으로 1화를 스위치가 꺼진 채 공개해 잠근 뒤 스위치를 켠 소설(3화짜리). 켜기 전에 공개된
    소설은 그때 잠겼으므로 켠 뒤에도 승인 대기가 없다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch, chapters=3)
    await _hand_source_to_someone_else(db_session, novel_id, "public")
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    _policy(monkeypatch, on=True)
    return novel_id, chapters


async def test_a_locked_novel_extends_after_the_source_withdraws_permission(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    novel_id, chapters = await _locked_on_someone_elses_source(db_client, db_session, monkeypatch)
    (await _source(db_session, novel_id)).novel_permission = "private"
    await db_session.commit()

    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    resp = await _publish(db_client, novel_id, chapters[1])

    assert (status_body["newPublishBlock"], status_body["reviewRequired"]) == (None, False)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["visibility"], body["publishedChapterCount"], body["reviewStatus"]) == ("public", 2, None)


async def test_a_locked_novel_still_stops_when_the_source_leaves_the_public_list(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """잠금이 면제하는 것은 소설화 허락 철회뿐이다. 원작자가 허락을 거두고 원작도 비공개로 돌리면 막는 이유는 허락이 아니라
    목록 조건이다 — 허락을 건너뛴 판정이 목록 조건까지 내려가 본다."""
    novel_id, chapters = await _locked_on_someone_elses_source(db_client, db_session, monkeypatch)
    source = await _source(db_session, novel_id)
    source.novel_permission = "private"
    source.visibility = ContentVisibility.PRIVATE
    await db_session.commit()

    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    resp = await _publish(db_client, novel_id, chapters[1])

    assert status_body["newPublishBlock"] == "source_not_listed"
    assert (resp.status_code, resp.json()["detail"]) == (
        409,
        {"code": "NOVEL_SOURCE_NOT_PUBLISHABLE", "reason": "source_not_listed"},
    )


async def test_another_unlocked_novel_from_the_same_source_needs_the_current_permission(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """잠금은 소설 하나에 걸린다. 같은 원작으로 만든 다른 소설은 잠기지 않았으므로 지금 허락을 따른다 — 잠긴 소설의 다음
    화는 같은 허락 아래에서 열린다."""
    locked_id, locked_chapters = await _locked_on_someone_elses_source(db_client, db_session, monkeypatch)
    locked_novel = await _novel_row(db_session, locked_id)
    locked_owner, content_id = locked_novel.user_id, locked_novel.content_id
    other_id, other_chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    await db_session.execute(sa.update(Novel).where(Novel.id == other_id).values(content_id=content_id))
    (await db_session.get_one(Content, content_id)).novel_permission = "private"
    await db_session.commit()

    other_status = (await db_client.get(f"/novels/{other_id}/publication")).json()
    other = await _publish(db_client, other_id, other_chapters[0])
    await _login_as(db_client, locked_owner)
    locked = await _publish(db_client, locked_id, locked_chapters[1])

    assert other_status["newPublishBlock"] == "source_permission"
    assert (other.status_code, other.json()["detail"]) == (
        403,
        {"code": "NOVEL_SOURCE_NOT_PUBLISHABLE", "reason": "source_permission"},
    )
    assert await _count(db_session, NovelPublication, other_id) == 0
    assert locked.status_code == 200, locked.text


async def test_own_source_needs_no_permission_with_the_switch_on_either(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    _policy(monkeypatch, on=True)
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    (await _source(db_session, novel_id)).novel_permission = "forbidden"
    await db_session.commit()

    status_body = (await db_client.get(f"/novels/{novel_id}/publication")).json()
    resp = await _publish(db_client, novel_id, chapters[0])

    assert status_body["newPublishBlock"] is None
    assert (resp.status_code, resp.json()["reviewStatus"]) == (200, "pending")


# ── 판 이력 ─────────────────────────────────────────────────────────────────
async def _editions(db_session: AsyncSession, novel_id: uuid.UUID) -> list[tuple[uuid.UUID, int, uuid.UUID, str | None, str]]:
    rows = await db_session.execute(
        sa.select(
            NovelChapterEdition.chapter_id,
            NovelChapterEdition.edition,
            NovelChapterEdition.revision_id,
            NovelChapterEdition.title,
            NovelChapterEdition.author_note,
        )
        .where(NovelChapterEdition.novel_id == novel_id)
        .order_by(NovelChapterEdition.chapter_id, NovelChapterEdition.edition)
        .execution_options(populate_existing=True)
    )
    return [(row[0], row[1], row[2], row[3], row[4]) for row in rows]


async def _publications(db_session: AsyncSession, novel_id: uuid.UUID) -> list[tuple[uuid.UUID, int, uuid.UUID, str | None, str]]:
    """지금 화 공개본들 — 판 행과 같은 모양으로."""
    rows = await db_session.execute(
        sa.select(
            NovelChapterPublication.chapter_id,
            NovelChapterPublication.edition,
            NovelChapterPublication.revision_id,
            NovelChapterPublication.title,
            NovelChapterPublication.author_note,
        )
        .where(NovelChapterPublication.novel_id == novel_id)
        .execution_options(populate_existing=True)
    )
    return [(row[0], row[1], row[2], row[3], row[4]) for row in rows]


async def test_every_first_and_later_publish_adds_one_edition_row_and_keeps_the_earlier_ones(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """정책 스위치가 꺼져 있어도 처음 공개·다음 화·다시 공개마다 그 판의 판 행이 하나씩 쌓이고(그때 화 공개본의 개정·제목·
    작가의 말 사본), 앞 판의 행은 다시 공개 뒤에도 그대로다. 바뀐 것이 없는 공개는 판 행을 더하지 않는다. 깨지는 시나리오:
    다시 공개가 판 행을 쓰지 않거나 앞 판 행을 덮어, 앞 판을 산 사람이 산 때의 글을 다시 읽을 수 없다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch)
    await db_session.execute(
        sa.update(NovelChapter).where(NovelChapter.id == chapters[0].id).values(title="첫 화", author_note="고마워요")
    )
    await db_session.commit()
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    assert (await _publish(db_client, novel_id, chapters[1])).status_code == 200
    first_publications = await _publications(db_session, novel_id)
    first_editions = await _editions(db_session, novel_id)

    edited = await _new_revision(db_session, chapters[0], "고친 첫 문단이다.")
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200
    assert (await _publish(db_client, novel_id, chapters[0])).status_code == 200

    assert sorted(first_editions) == sorted(first_publications)
    assert len(first_publications) == 2
    assert sorted(await _editions(db_session, novel_id)) == sorted(
        [*first_editions, (chapters[0].id, 2, edited.id, "첫 화", "고마워요")]
    )


async def test_revising_a_sold_chapter_publishes_a_new_edition_through_screening(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """팔린 6화를 고쳐 다시 공개하면 고친 글이 다시 심사를 거치고(심사 호출 하나) 새 판이 된다. 산 사람의 구매는 산 때의 판
    번호를 그대로 들고, 그 판의 판 행이 남아 있다. 깨지는 시나리오: 판매 뒤 개정이 심사 없이 나가거나, 산 때의 판이 사라진다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch, chapters=6)
    for chapter in chapters:
        assert (await _publish(db_client, novel_id, chapter)).status_code == 200
    owner = (await _novel_row(db_session, novel_id)).user_id
    buyer = await _make_user_with_clover_lot(db_session, clover_balance=100)
    await db_session.commit()
    await _login_as(db_client, buyer.id)
    bought = await db_client.post(
        f"/webnovels/{novel_id}/chapters/{chapters[5].id}/purchase", json={"expectedPrice": 30}
    )
    assert bought.status_code == 200, bought.text
    await _login_as(db_client, owner)
    screened_before = len(llm.calls)
    sold_revision = await db_session.scalar(
        sa.select(NovelChapterRevision.id).where(NovelChapterRevision.chapter_id == chapters[5].id)
    )

    edited = await _new_revision(db_session, chapters[5], "팔린 뒤 고친 6화.")
    resp = await _publish(db_client, novel_id, chapters[5])

    assert resp.status_code == 200, resp.text
    assert len(llm.calls) == screened_before + 1
    assert "팔린 뒤 고친 6화." in llm.calls[-1][1]
    sixth = [row for row in await _editions(db_session, novel_id) if row[0] == chapters[5].id]
    assert [(edition, revision_id) for _, edition, revision_id, _, _ in sixth] == [(1, sold_revision), (2, edited.id)]
    purchase_edition = await db_session.scalar(
        sa.select(NovelPurchase.edition).where(NovelPurchase.buyer_user_id == buyer.id)
    )
    assert purchase_edition == 1


@pytest.mark.parametrize("ending", ["reject", "cancel"])
async def test_a_rejected_or_cancelled_first_publish_leaves_no_edition_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM, ending: str
) -> None:
    """승인을 기다리는 첫 공개도 판 행을 쓰지만, 운영자가 반려하거나 작가가 신청을 취소하면 화 공개본과 함께 그 소설의 판
    행도 지운다 — 독자에게 보인 적 없는 판이다. 깨지는 시나리오: 반려된 글이 판 이력에 남아 다시 신청한 첫 판과 같은 판
    번호로 부딪히거나(500), 보인 적 없는 판이 "산 때의 판" 후보로 남는다."""
    novel_id, _chapters = await _pending(db_client, db_session, monkeypatch)
    waiting = len(await _editions(db_session, novel_id))
    if ending == "reject":
        await _as_admin(db_client, db_session)
        resp = await _review(db_client, novel_id, "reject", "고쳐서 다시 신청해 주세요.")
        assert resp.status_code == 200, resp.text
    else:
        assert (await db_client.post(f"/novels/{novel_id}/publication/withdraw")).status_code == 204

    assert waiting == 1
    assert await _editions(db_session, novel_id) == []


async def test_a_new_request_over_edition_rows_an_old_image_left_behind_replaces_them(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """배포가 겹치는 동안 판 이력 표를 모르는 옛 이미지가 승인 대기 공개를 반려하면 화 공개본만 지우고, 대기 공개가 쌓은
    1판 판 행은 남는다. 작가가 고쳐 다시 신청하면 화 공개본이 다시 1판으로 시작하는데, 남은 행과 부딪치지 않고 그 행을 새
    공개본으로 바꾼다. 깨지는 시나리오: 다시 신청이 (화, 1판) 판 행 충돌로 500 이 되어 그 소설은 다시 공개할 수 없다."""
    novel_id, chapters = await _pending(db_client, db_session, monkeypatch)
    # 옛 이미지의 반려 — 판 행은 모르고 화 공개본만 지운다.
    await db_session.execute(sa.delete(NovelChapterPublication).where(NovelChapterPublication.novel_id == novel_id))
    await db_session.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == novel_id)
        .values(review_status="rejected", review_reason="고쳐서 다시 신청해 주세요.", reviewed_at=sa.func.now())
    )
    await db_session.commit()
    left = await _editions(db_session, novel_id)
    edited = await _new_revision(db_session, chapters[0], "고쳐서 다시 낸 첫 화.")

    resp = await _publish(db_client, novel_id, chapters[0])

    assert [(chapter_id, edition) for chapter_id, edition, *_ in left] == [(chapters[0].id, 1)]
    assert resp.status_code == 200, resp.text
    editions = await _editions(db_session, novel_id)
    assert editions == await _publications(db_session, novel_id)
    assert [(chapter_id, edition, revision_id) for chapter_id, edition, revision_id, *_ in editions] == [
        (chapters[0].id, 1, edited.id)
    ]


# ── 화별 가격 ───────────────────────────────────────────────────────────────
async def _publish_priced(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, chapter: NovelChapter, *, free: bool | None
) -> httpx.Response:
    body: dict[str, object] = {"chapterId": str(chapter.id)}
    if free is not None:
        body["free"] = free
    return await db_client.post(f"/novels/{novel_id}/publication", json=body)


async def _make_free(db_client: httpx.AsyncClient, novel_id: uuid.UUID, chapter_id: uuid.UUID) -> httpx.Response:
    return await db_client.post(f"/novels/{novel_id}/publication/chapters/{chapter_id}/free")


async def _prices(db_session: AsyncSession, novel_id: uuid.UUID) -> dict[int, int]:
    rows = await db_session.execute(
        sa.select(NovelChapterPublication.ordinal, NovelChapterPublication.price)
        .where(NovelChapterPublication.novel_id == novel_id)
        .execution_options(populate_existing=True)
    )
    return {ordinal: price for ordinal, price in rows.tuples()}


async def _published_through(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    published: int,
    chapters: int = 8,
) -> tuple[uuid.UUID, list[NovelChapter]]:
    """화 `chapters` 개짜리 소설의 1화부터 `published` 화까지를 정책 스위치가 꺼진 채 공개한 뒤(바로 열리고 연재권이 잠긴다)
    스위치를 켠다 — 그 뒤의 공개는 승인 대기 없이 바로 열린다."""
    novel_id, added = await _novel_with_chapters(db_client, db_session, monkeypatch, chapters=chapters)
    for chapter in added[:published]:
        assert (await _publish(db_client, novel_id, chapter)).status_code == 200
    _policy(monkeypatch, on=True)
    return novel_id, added


async def test_from_the_sixth_chapter_the_publisher_picks_free_or_paid_and_free_stays_free(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """스위치가 켜지면 6화부터 새로 공개하는 화마다 무료를 고를 수 있고, 고르지 않으면 유료(화당 가격)다. 무료로 공개한 화를
    유료로 다시 내는 요청은 409 이고 값이 그대로다. 가격 칸 없이 그 화의 본문만 고쳐 다시 내면(옛 화면·옛 탭의 요청) 무료가
    유지되고, 거뒀다 다시 열어도 그대로다. 상태 응답이 공개 화마다 가격을 알린다. 깨지는 시나리오: 가격을 고르지 않은 요청이
    무료로 저장되거나, 다시 공개가 가격을 덮어 무료로 공개한 화가 유료가 된다."""
    novel_id, chapters = await _published_through(db_client, db_session, monkeypatch, published=5)

    free_sixth = await _publish_priced(db_client, novel_id, chapters[5], free=True)
    paid_seventh = await _publish_priced(db_client, novel_id, chapters[6], free=None)
    explicit_eighth = await _publish_priced(db_client, novel_id, chapters[7], free=False)
    back_to_paid = await _publish_priced(db_client, novel_id, chapters[5], free=False)
    await _new_revision(db_session, chapters[5], "고친 6화.")
    revised = await _publish_priced(db_client, novel_id, chapters[5], free=None)
    assert (await db_client.post(f"/novels/{novel_id}/publication/withdraw")).status_code == 204
    reopened = await _publish(db_client, novel_id, None)

    for resp in (free_sixth, paid_seventh, explicit_eighth, revised, reopened):
        assert resp.status_code == 200, resp.text
    assert (back_to_paid.status_code, back_to_paid.json()["detail"]) == (409, {"code": "NOVEL_CHAPTER_PRICE_LOCKED"})
    assert await _prices(db_session, novel_id) == {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 30, 8: 30}
    sixth = await db_session.get_one(NovelChapterPublication, chapters[5].id, populate_existing=True)
    assert (sixth.edition, sixth.price_changed_at) == (2, None)
    assert [(c["chapterId"], c["ordinal"], c["price"]) for c in reopened.json()["publishedChapters"]] == [
        (str(chapter.id), ordinal, 30 if ordinal in (7, 8) else 0)
        for ordinal, chapter in enumerate(chapters, start=1)
    ]


async def test_the_front_chapters_are_always_free(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """5화까지는 고를 수 없는 무료다 — 유료로 공개하려는 요청은 409 이고 아무것도 쓰지 않는다(심사도 부르지 않는다).
    깨지는 시나리오: 앞 화가 유료로 저장돼 "앞 화 무료" 약속이 깨진다."""
    novel_id, chapters = await _published_through(db_client, db_session, monkeypatch, published=4, chapters=5)
    screened = len(llm.calls)

    paid_fifth = await _publish_priced(db_client, novel_id, chapters[4], free=False)
    fifth = await _publish_priced(db_client, novel_id, chapters[4], free=None)

    assert (paid_fifth.status_code, paid_fifth.json()["detail"]) == (409, {"code": "NOVEL_CHAPTER_PRICE_LOCKED"})
    assert len(llm.calls) == screened + 1
    assert fifth.status_code == 200, fifth.text
    assert (await _prices(db_session, novel_id))[5] == 0


async def test_a_publish_request_cannot_make_an_already_published_paid_chapter_free(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """이미 유료로 공개한 화를 무료로 바꾸는 것은 따로 있는 "무료로 전환" 동작만 한다 — 공개 요청에 무료를 실으면 409 이고
    그대로 유료다. 깨지는 시나리오: 공개 요청의 가격 칸이 조용히 버려져 작가는 무료로 바꿨다고 알고 독자는 계속 산다."""
    novel_id, chapters = await _published_through(db_client, db_session, monkeypatch, published=6, chapters=6)

    resp = await _publish_priced(db_client, novel_id, chapters[5], free=True)

    assert (resp.status_code, resp.json()["detail"]) == (409, {"code": "NOVEL_CHAPTER_ALREADY_PRICED"})
    assert (await _prices(db_session, novel_id))[6] == 30


async def test_with_the_policy_off_the_price_choice_is_ignored_and_prices_follow_the_chapter_number(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """스위치가 꺼져 있으면 지금 약관대로 앞 5화는 무료, 6화부터는 화당 가격이다 — 요청의 가격 칸은 보지 않는다(무료를
    실어도 유료, 유료를 실어도 앞 화는 무료, 이미 공개한 유료 화에 무료를 실어도 그대로 다시 공개된다). 무료로 전환도
    409 다. 깨지는 시나리오: 약관 개정 전에 6화 이후 무료 공개가 먼저 열리거나, 꺼진 동안의 저장값이 지금 규칙과 달라진다."""
    novel_id, chapters = await _novel_with_chapters(db_client, db_session, monkeypatch, chapters=7)

    for chapter in chapters[:4]:
        assert (await _publish(db_client, novel_id, chapter)).status_code == 200
    paid_fifth = await _publish_priced(db_client, novel_id, chapters[4], free=False)
    free_sixth = await _publish_priced(db_client, novel_id, chapters[5], free=True)
    seventh = await _publish_priced(db_client, novel_id, chapters[6], free=None)
    await _new_revision(db_session, chapters[5], "고친 6화.")
    free_again = await _publish_priced(db_client, novel_id, chapters[5], free=True)
    made_free = await _make_free(db_client, novel_id, chapters[6].id)

    for resp in (paid_fifth, free_sixth, seventh, free_again):
        assert resp.status_code == 200, resp.text
    assert (made_free.status_code, made_free.json()["detail"]) == (409, {"code": "NOVEL_PRICE_CHOICE_DISABLED"})
    assert await _prices(db_session, novel_id) == {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 30, 7: 30}


async def test_making_a_paid_chapter_free_changes_only_its_price(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """유료로 공개한 6화를 "무료로 전환"하면 그 화의 가격만 0 이 되고 바꾼 시각이 남는다. 심사를 부르지 않고, 판도 판 행도
    그대로이며, 공개 상태(거둔 상태 포함)와 공개 시각도 그대로다 — 거둔 소설을 다시 열지 않는다. 다시 눌러도 같다. 깨지는
    시나리오: 가격만 바꾸는 일이 공개 흐름을 타 심사가 걸리고 판이 오르고 최신순 목록 자리가 바뀌거나, 거둔 소설이 다시
    열린다."""
    novel_id, chapters = await _published_through(db_client, db_session, monkeypatch, published=7, chapters=7)
    assert (await db_client.post(f"/novels/{novel_id}/publication/withdraw")).status_code == 204
    publication_before = await _publication_row(db_session, novel_id)
    assert publication_before is not None
    before = (publication_before.visibility, publication_before.published_at)
    editions_before = await _editions(db_session, novel_id)
    screened = len(llm.calls)

    resp = await _make_free(db_client, novel_id, chapters[5].id)
    sixth = await db_session.get_one(NovelChapterPublication, chapters[5].id, populate_existing=True)
    changed_at = sixth.price_changed_at
    again = await _make_free(db_client, novel_id, chapters[5].id)

    assert resp.status_code == 200, resp.text
    assert [(c["ordinal"], c["price"]) for c in resp.json()["publishedChapters"]][5:] == [(6, 0), (7, 30)]
    assert again.status_code == 200, again.text
    assert await _prices(db_session, novel_id) == {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 30}
    sixth = await db_session.get_one(NovelChapterPublication, chapters[5].id, populate_existing=True)
    assert (sixth.edition, sixth.price_changed_at) == (1, changed_at)
    assert changed_at is not None
    assert len(llm.calls) == screened
    assert await _editions(db_session, novel_id) == editions_before
    publication_after = await _publication_row(db_session, novel_id)
    assert publication_after is not None
    assert (publication_after.visibility, publication_after.published_at) == before


async def test_making_free_needs_a_published_chapter_of_ones_own_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """무료로 전환은 게시자 본인이 공개한 화에만 된다 — 공개하지 않은 화는 404, 남의 소설은 403 이다. 이미 무료인 앞 화는
    아무것도 쓰지 않는다(바꾼 시각이 남지 않는다). 깨지는 시나리오: 남이 작가의 유료 화를 무료로 돌리거나, 공개 전 화에
    가격이 먼저 생긴다."""
    novel_id, chapters = await _published_through(db_client, db_session, monkeypatch, published=6, chapters=7)
    others = Novel(
        user_id=(await _make_stranger(db_session)).id,
        content_id=uuid.uuid4(),
        content_type="character",
        content_title="남의 원작",
    )
    db_session.add(others)
    await db_session.commit()

    unpublished = await _make_free(db_client, novel_id, chapters[6].id)
    front = await _make_free(db_client, novel_id, chapters[2].id)
    foreign = await _make_free(db_client, others.id, uuid.uuid4())

    assert (unpublished.status_code, unpublished.json()["detail"]["code"]) == (404, "NOVEL_CHAPTER_NOT_FOUND")
    assert front.status_code == 200, front.text
    third = await db_session.get_one(NovelChapterPublication, chapters[2].id, populate_existing=True)
    assert (third.price, third.price_changed_at) == (0, None)
    assert (foreign.status_code, foreign.json()["detail"]["code"]) == (403, "NOVEL_FORBIDDEN")
