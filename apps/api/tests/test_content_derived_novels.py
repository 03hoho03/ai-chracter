"""원작 상세의 공개 소설 목록(`GET /contents/{id}/derived-novels`)과 원작자의 숨김(`PUT /contents/{id}/derived-novels-visibility`).

목록에는 노벨 목록과 같은 조건으로 지금 독자가 읽을 수 있는 소설만 나간다. 노벨이 읽는 사람에게 닫혀 있으면(스위치 꺼짐,
미리보기 명단 밖) 오류가 아니라 빈 목록이다 — 원작 상세는 노벨 화면이 아니라 이 목록이 비면 영역을 그리지 않으면 된다.
원작자가 숨기면 다른 사람에게는 비고, 원작자 본인에게는 무엇이 걸려 있는지 보이게 항목을 그대로 준다.

공개 소설은 `_make_public_novel`(화 하나짜리 묶음)로 만든 뒤 원작 id 를 이 테스트의 작품으로 옮긴다."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import Content, ModerationStatus, User
from api.db.models.novel import Novel, NovelChapterPublication, NovelPublication
from factories import _get_genre, _login_as, _make_public_novel, _make_published_character, _make_user

_LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _novel_public_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_public_enabled", True)
    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [])


async def _member(db_session: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    return user.id


async def _work(db_session: AsyncSession) -> Content:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()
    return content


async def _derived(
    db_session: AsyncSession,
    content_id: uuid.UUID,
    *,
    publisher_id: uuid.UUID | None = None,
    published_at: datetime | None = None,
) -> uuid.UUID:
    """`content_id` 를 원작으로 하는 공개 소설 하나(커밋). 게시자를 주지 않으면 새 회원이다."""
    if publisher_id is None:
        publisher = _make_user()
        db_session.add(publisher)
        await db_session.flush()
        publisher_id = publisher.id
    novel = await _make_public_novel(db_session, publisher_id, batches=(1,))
    await db_session.execute(sa.update(Novel).where(Novel.id == novel.novel_id).values(content_id=content_id))
    if published_at is not None:
        await db_session.execute(
            sa.update(NovelPublication)
            .where(NovelPublication.novel_id == novel.novel_id)
            .values(published_at=published_at)
        )
    await db_session.commit()
    return novel.novel_id


async def _list(client: httpx.AsyncClient, content_id: uuid.UUID, *, as_user: uuid.UUID, **params: str) -> httpx.Response:
    await _login_as(client, as_user)
    return await client.get(f"/contents/{content_id}/derived-novels", params=params)


async def _listed(client: httpx.AsyncClient, content_id: uuid.UUID, *, as_user: uuid.UUID) -> list[str]:
    resp = await _list(client, content_id, as_user=as_user)
    assert resp.status_code == 200
    return [item["id"] for item in resp.json()["items"]]


async def _hide(client: httpx.AsyncClient, content: Content, *, visible: bool = False) -> httpx.Response:
    await _login_as(client, content.creator_user_id)
    return await client.put(f"/contents/{content.id}/derived-novels-visibility", json={"visible": visible})


# ── 목록 ────────────────────────────────────────────────────────────────────
async def test_lists_readable_novels_of_this_work_newest_first_and_marks_the_creators_own(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이 작품을 원작으로 한 공개 소설만 공개 시각 늦은 순으로 나가고, 원작자 본인이 낸 소설만 비공식 표시가 없다. 읽는
    사람은 소설화 허용이 없는 일반 회원이다 — 소설화 게이트에 걸리지 않는다."""
    content = await _work(db_session)
    other_work = await _work(db_session)
    now = datetime.now(UTC)
    fan = await _derived(db_session, content.id, published_at=now - timedelta(hours=1))
    official = await _derived(db_session, content.id, publisher_id=content.creator_user_id, published_at=now)
    await _derived(db_session, other_work.id)
    reader = await _member(db_session)

    resp = await _list(db_client, content.id, as_user=reader)

    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body["items"]] == [str(official), str(fan)]
    assert [item["source"]["unofficial"] for item in body["items"]] == [False, True]
    assert body["visible"] is True and body["nextCursor"] is None


Hide = Callable[[AsyncSession, uuid.UUID], Awaitable[None]]


async def _drop_publication(db: AsyncSession, novel_id: uuid.UUID) -> None:
    await db.execute(sa.delete(NovelChapterPublication).where(NovelChapterPublication.novel_id == novel_id))
    await db.execute(sa.delete(NovelPublication).where(NovelPublication.novel_id == novel_id))


async def _withdraw(db: AsyncSession, novel_id: uuid.UUID) -> None:
    await db.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == novel_id).values(visibility="withdrawn")
    )


async def _restrict(db: AsyncSession, novel_id: uuid.UUID) -> None:
    await db.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == novel_id).values(moderation_status="restricted")
    )


async def _await_review(db: AsyncSession, novel_id: uuid.UUID) -> None:
    await db.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == novel_id)
        .values(visibility="withdrawn", review_status="pending")
    )


async def _reject(db: AsyncSession, novel_id: uuid.UUID) -> None:
    await db.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == novel_id)
        .values(visibility="withdrawn", review_status="rejected", review_reason="합성 반려 사유")
    )


async def _hide_novel(db: AsyncSession, novel_id: uuid.UUID) -> None:
    await db.execute(sa.update(Novel).where(Novel.id == novel_id).values(hidden_at=sa.func.now()))


@pytest.mark.parametrize(
    "hide",
    [
        pytest.param(_drop_publication, id="never-published"),
        pytest.param(_withdraw, id="withdrawn"),
        pytest.param(_restrict, id="restricted"),
        pytest.param(_await_review, id="review-pending"),
        pytest.param(_reject, id="review-rejected"),
        pytest.param(_hide_novel, id="novel-hidden"),
    ],
)
async def test_a_novel_readers_cannot_read_is_left_out(
    db_client: httpx.AsyncClient, db_session: AsyncSession, hide: Hide
) -> None:
    """같은 작품의 두 소설 중 하나만 숨김 조건을 걸면 그 하나만 빠진다(남은 하나가 목록이 통째로 비는 실패와 가른다)."""
    content = await _work(db_session)
    shown = await _derived(db_session, content.id)
    gone = await _derived(db_session, content.id)
    reader = await _member(db_session)
    assert sorted(await _listed(db_client, content.id, as_user=reader)) == sorted([str(shown), str(gone)])

    await hide(db_session, gone)
    await db_session.commit()

    assert await _listed(db_client, content.id, as_user=reader) == [str(shown)]


async def test_a_reader_the_novel_section_is_closed_to_gets_an_empty_list(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """노벨 스위치가 꺼졌거나 미리보기 명단 밖이면 오류가 아니라 빈 목록이고, 명단 안의 회원에게는 같은 소설이 나간다."""
    content = await _work(db_session)
    novel = await _derived(db_session, content.id)
    reader = await _member(db_session)

    monkeypatch.setattr(settings, "novel_public_enabled", False)
    off = await _list(db_client, content.id, as_user=reader)
    assert off.status_code == 200 and off.json()["items"] == []

    monkeypatch.setattr(settings, "novel_public_enabled", True)
    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [uuid.uuid4()])
    outside = await _list(db_client, content.id, as_user=reader)
    assert outside.status_code == 200 and outside.json()["items"] == []

    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [reader])
    assert await _listed(db_client, content.id, as_user=reader) == [str(novel)]


async def test_the_list_needs_login_and_a_missing_work_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content = await _work(db_session)
    await _derived(db_session, content.id)
    reader = await _member(db_session)

    anonymous = await db_client.get(f"/contents/{content.id}/derived-novels")
    missing = await _list(db_client, uuid.uuid4(), as_user=reader)

    assert anonymous.status_code == 401
    assert missing.status_code == 404


async def test_the_list_pages_with_a_cursor_without_repeats(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("api.novel_public.derived.DERIVED_NOVEL_PAGE_SIZE", 2)
    content = await _work(db_session)
    now = datetime.now(UTC)
    oldest = await _derived(db_session, content.id, published_at=now - timedelta(hours=2))
    middle = await _derived(db_session, content.id, published_at=now - timedelta(hours=1))
    newest = await _derived(db_session, content.id, published_at=now)
    reader = await _member(db_session)

    first = await _list(db_client, content.id, as_user=reader)
    cursor = first.json()["nextCursor"]
    second = await _list(db_client, content.id, as_user=reader, cursor=cursor)
    broken = await _list(db_client, content.id, as_user=reader, cursor="not-a-cursor")

    assert [item["id"] for item in first.json()["items"]] == [str(newest), str(middle)]
    assert [item["id"] for item in second.json()["items"]] == [str(oldest)]
    assert second.json()["nextCursor"] is None
    assert (broken.status_code, broken.json()["detail"]["code"]) == (422, "INVALID_CURSOR")


# ── 원작자 숨김 ──────────────────────────────────────────────────────────────
async def test_hidden_list_is_empty_for_others_and_still_shown_to_the_creator(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """숨기면 다른 회원에게 빈 목록이고 원작자에게는 항목과 숨김 상태가 함께 나간다. 다시 켜면 돌아온다. 작품 상세도 지금
    값을 싣는다."""
    content = await _work(db_session)
    novel = await _derived(db_session, content.id)
    reader = await _member(db_session)

    hidden = await _hide(db_client, content)
    assert hidden.status_code == 204

    to_reader = await _list(db_client, content.id, as_user=reader)
    assert to_reader.json() == {"visible": False, "items": [], "nextCursor": None}
    to_creator = await _list(db_client, content.id, as_user=content.creator_user_id)
    assert to_creator.json()["visible"] is False
    assert [item["id"] for item in to_creator.json()["items"]] == [str(novel)]
    detail = await db_client.get(f"/contents/{content.id}")
    assert detail.json()["derivedNovelsVisible"] is False

    shown = await _hide(db_client, content, visible=True)
    assert shown.status_code == 204
    assert await _listed(db_client, content.id, as_user=reader) == [str(novel)]
    detail = await db_client.get(f"/contents/{content.id}")
    assert detail.json()["derivedNovelsVisible"] is True


async def test_hiding_changes_only_the_display_and_moves_the_last_edit_forward(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """숨김은 표시만 줄인다 — 작품의 소설화 허락, 소설의 권리 고정 칸과 공개 상태는 그대로다. 작가가 작품 설정을 바꾼
    것이라 마지막 편집 시각은 앞으로 간다."""
    content = await _work(db_session)
    novel_id = await _derived(db_session, content.id)
    locked_at = datetime(2026, 5, 1, tzinfo=UTC)
    await db_session.execute(
        sa.update(Content).where(Content.id == content.id).values(novel_permission="public", edited_at=_LONG_AGO)
    )
    await db_session.execute(
        sa.update(Novel)
        .where(Novel.id == novel_id)
        .values(
            writing_locked_at=locked_at,
            writing_lock_permission="public",
            writing_lock_source="first_chapter",
            serial_locked_at=locked_at,
            serial_lock_permission="public",
            serial_lock_source="first_publish",
        )
    )
    await db_session.commit()

    resp = await _hide(db_client, content)

    assert resp.status_code == 204
    row = (
        await db_session.execute(
            sa.select(Content.novel_permission, Content.derived_novels_visible, Content.edited_at).where(
                Content.id == content.id
            )
        )
    ).one()
    assert (row.novel_permission, row.derived_novels_visible) == ("public", False)
    assert row.edited_at > _LONG_AGO
    locks = (
        await db_session.execute(
            sa.select(
                Novel.writing_locked_at,
                Novel.writing_lock_permission,
                Novel.serial_locked_at,
                Novel.serial_lock_permission,
            ).where(Novel.id == novel_id)
        )
    ).one()
    assert tuple(locks) == (locked_at, "public", locked_at, "public")
    visibility = await db_session.scalar(
        sa.select(NovelPublication.visibility).where(NovelPublication.novel_id == novel_id)
    )
    assert visibility == "public"


async def test_only_the_creator_hides_and_a_missing_work_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content = await _work(db_session)
    other = await _member(db_session)
    await _login_as(db_client, other)

    forbidden = await db_client.put(f"/contents/{content.id}/derived-novels-visibility", json={"visible": False})
    missing = await db_client.put(f"/contents/{uuid.uuid4()}/derived-novels-visibility", json={"visible": False})

    assert (forbidden.status_code, forbidden.json()["detail"]) == (403, "Not the content owner")
    assert (missing.status_code, missing.json()["detail"]) == (404, "Content not found")
    stored = await db_session.scalar(sa.select(Content.derived_novels_visible).where(Content.id == content.id))
    assert stored is True


async def test_a_suspended_creator_cannot_hide(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """세션 검사(Redis 정지 표식)를 지난 뒤에도 회원 행의 정지를 다시 본다 — 표식 없이 DB 만 정지인 상태로 만든다."""
    content = await _work(db_session)
    await db_session.execute(
        sa.update(User).where(User.id == content.creator_user_id).values(suspended_at=sa.func.now())
    )
    await db_session.commit()

    resp = await _hide(db_client, content)

    assert (resp.status_code, resp.json()["detail"]) == (403, "Account suspended")


async def test_a_restricted_work_can_still_be_hidden(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """숨김은 노출을 줄이는 쪽이라 이용제한 중에도 막지 않는다."""
    content = await _work(db_session)
    await db_session.execute(
        sa.update(Content).where(Content.id == content.id).values(moderation_status=ModerationStatus.RESTRICTED)
    )
    await db_session.commit()

    resp = await _hide(db_client, content)

    assert resp.status_code == 204
