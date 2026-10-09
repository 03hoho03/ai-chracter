"""노벨 독자 라우트 — 목록·작품 정보·화 읽기·읽은 자리·좋아요·조회 수·홈 노벨, 그리고 열람 종료 안내.

공개 소설은 `_make_public_novel`(원작 = 다른 회원의 공개 작품, 6화 + 2화 묶음, 전부 공개)로 만든다. 앞 5화가 무료라 6화가
첫 유료 화이고, 본문은 "n화 본문" 이다. 같은 `db_client` 로 회원을 바꿔 가며 부른다(`_login_as`)."""

import uuid
from collections.abc import Awaitable, Callable

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import home_novel_curation
from api.core.config import settings
from api.db.models import AdminActionLog, User
from api.db.models.character import CharacterVersionDetail
from api.db.models.content import Content, ContentVersion, ContentVisibility, ModerationStatus
from api.db.models.novel import (
    HomeNovelCuration,
    NovelChapterPublication,
    NovelLike,
    NovelPublication,
    NovelReaderPosition,
)
from api.novel_public import reading
from api.novelize.deletion import delete_novels
from factories import (
    PublicNovel,
    _allow_novelize,
    _create_admin,
    _login_as,
    _login_as_admin,
    _make_asset,
    _make_public_novel,
    _make_user,
    _make_user_with_clover_lot,
)


@pytest.fixture(autouse=True)
def _novel_public_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_public_enabled", True)


async def _member(db_session: AsyncSession, balance: int = 100) -> uuid.UUID:
    user = await _make_user_with_clover_lot(db_session, clover_balance=balance)
    await db_session.commit()
    return user.id


async def _novel(db_session: AsyncSession, *, batches: tuple[int, ...] = (6, 2)) -> PublicNovel:
    publisher = _make_user()
    db_session.add(publisher)
    await db_session.flush()
    novel = await _make_public_novel(db_session, publisher.id, batches=batches)
    await db_session.commit()
    return novel


async def _get(client: httpx.AsyncClient, path: str, *, as_user: uuid.UUID) -> httpx.Response:
    await _login_as(client, as_user)
    return await client.get(path)


def _chapter_path(novel: PublicNovel, ordinal: int) -> str:
    return f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[ordinal - 1]}"


async def _listed_ids(client: httpx.AsyncClient, *, as_user: uuid.UUID) -> list[str]:
    resp = await _get(client, "/webnovels", as_user=as_user)
    assert resp.status_code == 200
    return [item["id"] for item in resp.json()["items"]]


async def _buy_sixth(client: httpx.AsyncClient, novel: PublicNovel, buyer: uuid.UUID) -> None:
    await _login_as(client, buyer)
    resp = await client.post(f"{_chapter_path(novel, 6)}/purchase", json={"expectedPrice": 30})
    assert resp.status_code == 200


# ── 숨김 조건 ────────────────────────────────────────────────────────────────
Hide = Callable[[AsyncSession, PublicNovel], Awaitable[None]]


async def _withdraw(db: AsyncSession, novel: PublicNovel) -> None:
    await db.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == novel.novel_id).values(visibility="withdrawn")
    )


async def _restrict(db: AsyncSession, novel: PublicNovel) -> None:
    await db.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == novel.novel_id)
        .values(moderation_status="restricted")
    )


async def _suspend_publisher(db: AsyncSession, novel: PublicNovel) -> None:
    await db.execute(sa.update(User).where(User.id == novel.publisher_id).values(suspended_at=sa.func.now()))


async def _restrict_source(db: AsyncSession, novel: PublicNovel) -> None:
    await db.execute(
        sa.update(Content).where(Content.id == novel.content_id).values(moderation_status=ModerationStatus.RESTRICTED)
    )


async def _delete_source(db: AsyncSession, novel: PublicNovel) -> None:
    await db.execute(
        sa.update(Content).where(Content.id == novel.content_id).values(moderation_status=ModerationStatus.DELETED)
    )


async def _drop_every_public_chapter(db: AsyncSession, novel: PublicNovel) -> None:
    await db.execute(sa.delete(NovelChapterPublication).where(NovelChapterPublication.novel_id == novel.novel_id))


_HIDES = [
    pytest.param(_withdraw, id="withdrawn"),
    pytest.param(_restrict, id="restricted"),
    pytest.param(_suspend_publisher, id="publisher-suspended"),
    pytest.param(_restrict_source, id="source-restricted"),
    pytest.param(_delete_source, id="source-deleted"),
    pytest.param(_drop_every_public_chapter, id="no-public-chapter"),
]


@pytest.mark.parametrize("hide", _HIDES)
async def test_each_hiding_condition_takes_the_novel_out_of_every_reader_route(
    db_client: httpx.AsyncClient, db_session: AsyncSession, hide: Hide
) -> None:
    """목록에 있던 노벨이 숨김 조건 하나로 목록·작품 정보·화·좋아요에서 함께 사라진다. 소장하지 않은 사람에게는 이유 없이
    404 다."""
    novel = await _novel(db_session)
    reader = await _member(db_session)
    assert await _listed_ids(db_client, as_user=reader) == [str(novel.novel_id)]

    await hide(db_session, novel)
    await db_session.commit()

    assert await _listed_ids(db_client, as_user=reader) == []
    detail = await db_client.get(f"/webnovels/{novel.novel_id}")
    chapter = await db_client.get(_chapter_path(novel, 1))
    like = await db_client.post(f"/webnovels/{novel.novel_id}/like")
    assert (detail.status_code, detail.json()["detail"]) == (404, {"code": "NOVEL_NOT_FOUND"})
    assert chapter.status_code == 404
    assert like.status_code == 404


async def test_source_made_private_keeps_the_novel_readable(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """원작자가 원작을 비공개로 돌리기만 했으면 기존 공개 소설은 그대로 읽힌다 — 원작 링크만 걸 수 없게 된다."""
    novel = await _novel(db_session)
    reader = await _member(db_session)
    await db_session.execute(
        sa.update(Content).where(Content.id == novel.content_id).values(visibility=ContentVisibility.PRIVATE)
    )
    await db_session.commit()

    resp = await _get(db_client, f"/webnovels/{novel.novel_id}", as_user=reader)

    assert resp.status_code == 200
    assert resp.json()["source"]["linkable"] is False


# ── 작품 정보 ───────────────────────────────────────────────────────────────
async def test_detail_shows_frozen_copies_and_each_chapter_state_for_the_reader(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """제목·소개는 공개본 사본이고(소유자가 고친 소설 제목은 나가지 않는다), 목차의 화마다 무료·소장·잠김과 가격이 붙는다."""
    novel = await _novel(db_session)
    reader = await _member(db_session)
    await _buy_sixth(db_client, novel, reader)
    await db_session.execute(
        sa.text("UPDATE novels SET title = '고쳤지만 다시 공개 안 한 제목' WHERE id = :id"), {"id": novel.novel_id}
    )
    await db_session.commit()

    body = (await _get(db_client, f"/webnovels/{novel.novel_id}", as_user=reader)).json()

    assert (body["title"], body["synopsis"], body["isPublisher"]) == ("공개 제목", "소개", False)
    assert [(c["ordinal"], c["access"], c["price"]) for c in body["chapters"]] == [
        (1, "free", None),
        (2, "free", None),
        (3, "free", None),
        (4, "free", None),
        (5, "free", None),
        (6, "owned", 30),
        (7, "locked", 30),
        (8, "locked", 30),
    ]
    assert (body["freeChapterCount"], body["chapterPrice"], body["likeCount"], body["liked"]) == (5, 30, 0, False)
    # 소유자 전용 칸(화 요약·인물 카드·소설 생성 표지)은 이 응답에 없다.
    assert not {"summary", "characters", "cover"} & (set(body) | set(body["chapters"][0]))


async def test_the_publisher_reads_every_chapter_without_buying(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    novel = await _novel(db_session)

    detail = (await _get(db_client, f"/webnovels/{novel.novel_id}", as_user=novel.publisher_id)).json()
    chapter = (await db_client.get(_chapter_path(novel, 8))).json()

    assert detail["isPublisher"] is True
    assert {c["access"] for c in detail["chapters"]} == {"publisher"}
    assert chapter["paragraphs"] == ["8화 본문"]


async def test_cover_is_the_source_thumbnail_until_the_source_creator_withdraws(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """표지는 원작 썸네일이다. 원작자가 탈퇴하면 그 원작의 노벨은 계속 읽히지만 표지는 비어(기본 표지) 탈퇴 회원의 그림이
    나가지 않는다."""
    novel = await _novel(db_session)
    reader = await _member(db_session)
    source = await db_session.get_one(Content, novel.content_id)
    version = ContentVersion(content_id=source.id, version_number=1, detail_description="설명")
    db_session.add(version)
    await db_session.flush()
    thumbnail = await _make_asset(db_session, owner_user_id=source.creator_user_id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="캐릭터",
            one_liner="한줄",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    source.current_published_version_id = version.id
    await db_session.commit()

    before = (await _get(db_client, f"/webnovels/{novel.novel_id}", as_user=reader)).json()
    await db_session.execute(sa.update(User).where(User.id == source.creator_user_id).values(deleted_at=sa.func.now()))
    await db_session.commit()
    after = await db_client.get(f"/webnovels/{novel.novel_id}")
    listed = (await db_client.get("/webnovels")).json()["items"]

    assert "_thumb.webp" in before["source"]["coverUrl"]
    assert after.status_code == 200
    assert after.json()["source"]["coverUrl"] is None
    assert listed[0]["source"]["coverUrl"] is None


# ── 화 읽기 ─────────────────────────────────────────────────────────────────
async def test_a_locked_chapter_carries_no_body_and_a_free_one_does(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """잠긴 화 응답에는 본문·작가의 말이 한 글자도 없고 가격만 있다. 다음 화가 잠겼으면 링크가 그것을 알린다."""
    novel = await _novel(db_session)
    reader = await _member(db_session)
    await db_session.execute(
        sa.update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == novel.chapter_ids[5])
        .values(author_note="6화 작가의 말")
    )
    await db_session.commit()

    locked = await _get(db_client, _chapter_path(novel, 6), as_user=reader)
    fifth = (await db_client.get(_chapter_path(novel, 5))).json()

    assert locked.status_code == 200
    assert (locked.json()["access"], locked.json()["price"], locked.json()["paragraphs"]) == ("locked", 30, None)
    assert "6화 본문" not in locked.text and "6화 작가의 말" not in locked.text
    assert (fifth["access"], fifth["paragraphs"]) == ("free", ["5화 본문"])
    assert fifth["nextChapter"] == {"id": str(novel.chapter_ids[5]), "ordinal": 6, "access": "locked"}


async def test_buying_opens_the_body_of_the_frozen_revision(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """소장하면 같은 주소에서 본문이 열린다. 본문은 공개 때 얼린 개정이다 — 소유자가 새 개정을 쌓아도 다시 공개 전에는 옛 글이다."""
    novel = await _novel(db_session)
    reader = await _member(db_session)
    await db_session.execute(
        sa.text(
            "INSERT INTO novel_chapter_revisions (id, chapter_id, revision_no, body, source)"
            " VALUES (gen_random_uuid(), :chapter, 2, '고친 본문', 'manual_edit')"
        ),
        {"chapter": novel.chapter_ids[5]},
    )
    await db_session.commit()
    await _buy_sixth(db_client, novel, reader)

    body = (await db_client.get(_chapter_path(novel, 6))).json()

    assert (body["access"], body["paragraphs"], body["edition"]) == ("owned", ["6화 본문"], 1)


# ── 열람 종료 ───────────────────────────────────────────────────────────────
async def _service_off(db: AsyncSession, novel: PublicNovel) -> None:
    settings.novel_public_enabled = False


_ENDINGS = [
    pytest.param(_withdraw, "withdrawn", id="withdrawn"),
    pytest.param(_restrict, "restricted", id="restricted"),
    pytest.param(_suspend_publisher, "restricted", id="publisher-suspended"),
    pytest.param(_restrict_source, "source_unavailable", id="source-restricted"),
    pytest.param(_service_off, "service_off", id="service-off"),
]


@pytest.mark.parametrize(("end", "reason"), _ENDINGS)
async def test_only_a_buyer_learns_why_reading_ended(
    db_client: httpx.AsyncClient, db_session: AsyncSession, end: Hide, reason: str
) -> None:
    """읽을 수 없게 된 노벨을 소장한 사람은 410 과 이유를, 소장하지 않은 사람은 같은 주소에서 이유 없는 404 를 받는다(작품
    정보·화 모두). 운영 조치와 게시자 정지는 같은 이유로 묶인다."""
    novel = await _novel(db_session)
    buyer, stranger = await _member(db_session), await _member(db_session)
    await _buy_sixth(db_client, novel, buyer)

    await end(db_session, novel)
    await db_session.commit()

    ended = {"code": "NOVEL_READING_ENDED", "reason": reason}
    for path in (f"/webnovels/{novel.novel_id}", _chapter_path(novel, 6), _chapter_path(novel, 1)):
        as_buyer = await _get(db_client, path, as_user=buyer)
        as_stranger = await _get(db_client, path, as_user=stranger)
        assert (as_buyer.status_code, as_buyer.json()["detail"]) == (410, ended), path
        assert as_stranger.status_code == 404, path
        assert "reason" not in as_stranger.json()["detail"], path


async def test_a_buyer_of_a_deleted_chapter_is_told_it_was_refunded(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """게시자가 소설을 지우면 산 사람은 "지워져 돌려받았다"와 돌려받은 양을 받는다. 노벨을 꺼 둔 동안에도 같다 — 지워진 것은
    다시 켜도 돌아오지 않는다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _buy_sixth(db_client, novel, buyer)
    await _login_as(db_client, novel.publisher_id)
    assert (await db_client.delete(f"/novels/{novel.novel_id}")).status_code == 204
    settings.novel_public_enabled = False

    chapter = await _get(db_client, _chapter_path(novel, 6), as_user=buyer)
    detail = await db_client.get(f"/webnovels/{novel.novel_id}")

    expected = {"code": "NOVEL_READING_ENDED", "reason": "deleted", "refundedAmount": 30}
    assert (chapter.status_code, chapter.json()["detail"]) == (410, expected)
    assert (detail.status_code, detail.json()["detail"]) == (410, expected)


async def test_a_buyer_learns_the_publisher_left_and_nothing_was_refunded(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _buy_sixth(db_client, novel, buyer)
    await _login_as(db_client, novel.publisher_id)
    assert (await db_client.delete("/me")).status_code == 204

    resp = await _get(db_client, _chapter_path(novel, 6), as_user=buyer)

    assert (resp.status_code, resp.json()["detail"]) == (
        410,
        {"code": "NOVEL_READING_ENDED", "reason": "publisher_withdrawn"},
    )


# ── 읽은 자리 ───────────────────────────────────────────────────────────────
async def test_reading_position_is_saved_and_restored_per_reader(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """저장한 자리가 작품 정보의 목차·이어 읽기와 화 응답에 돌아온다. 다 읽은 화는 앞부분을 다시 저장해도 다 읽은 화이고,
    다른 독자의 자리와 섞이지 않는다."""
    novel = await _novel(db_session)
    reader, other = await _member(db_session), await _member(db_session)
    path = f"{_chapter_path(novel, 2)}/reading-position"
    await _login_as(db_client, reader)
    first = await db_client.put(path, json={"paragraphIndex": 0, "paragraphCount": 1, "edition": 1, "finished": True})
    again = await db_client.put(path, json={"paragraphIndex": 0, "paragraphCount": 4, "edition": 1, "finished": False})

    detail = (await db_client.get(f"/webnovels/{novel.novel_id}")).json()
    chapter = (await db_client.get(_chapter_path(novel, 2))).json()
    others = (await _get(db_client, f"/webnovels/{novel.novel_id}", as_user=other)).json()

    assert (first.status_code, again.status_code) == (204, 204)
    restored = {"paragraphIndex": 0, "paragraphCount": 4, "edition": 1, "finished": True}
    assert detail["chapters"][1]["readingPosition"] == restored
    assert chapter["readingPosition"] == restored
    assert {k: detail["lastRead"][k] for k in ("chapterId", "ordinal")} == {
        "chapterId": str(novel.chapter_ids[1]),
        "ordinal": 2,
    }
    assert others["lastRead"] is None


async def test_reading_position_needs_a_chapter_the_reader_can_open(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    novel = await _novel(db_session)
    reader = await _member(db_session)
    await _login_as(db_client, reader)
    body = {"paragraphIndex": 0, "paragraphCount": 1, "edition": 1, "finished": False}

    locked = await db_client.put(f"{_chapter_path(novel, 7)}/reading-position", json=body)
    past_end = await db_client.put(
        f"{_chapter_path(novel, 1)}/reading-position", json={**body, "paragraphIndex": 1}
    )
    unknown = await db_client.put(f"/webnovels/{novel.novel_id}/chapters/{uuid.uuid4()}/reading-position", json=body)

    assert (locked.status_code, locked.json()["detail"]) == (403, {"code": "NOVEL_CHAPTER_LOCKED"})
    assert past_end.status_code == 422
    assert unknown.status_code == 404
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelReaderPosition)) == 0


# ── 탈퇴·삭제 정리 ──────────────────────────────────────────────────────────
async def test_a_withdrawing_reader_loses_positions_but_likes_stay(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    novel = await _novel(db_session)
    reader = await _member(db_session)
    await _login_as(db_client, reader)
    await db_client.put(
        f"{_chapter_path(novel, 1)}/reading-position",
        json={"paragraphIndex": 0, "paragraphCount": 1, "edition": 1, "finished": False},
    )
    assert (await db_client.post(f"/webnovels/{novel.novel_id}/like")).status_code == 204

    assert (await db_client.delete("/me")).status_code == 204

    positions = sa.select(sa.func.count()).select_from(NovelReaderPosition)
    assert await db_session.scalar(positions.where(NovelReaderPosition.user_id == reader)) == 0
    assert await db_session.scalar(sa.select(NovelLike.user_id).where(NovelLike.novel_id == novel.novel_id)) == reader
    assert await db_session.scalar(
        sa.select(NovelPublication.like_count).where(NovelPublication.novel_id == novel.novel_id)
    ) == 1


async def _plant_reader_rows(client: httpx.AsyncClient, db: AsyncSession, novel: PublicNovel, reader: uuid.UUID) -> None:
    """독자 하나가 7화(마지막 묶음)를 읽던 자리·좋아요를 남기고, 소설을 홈 노벨 1번 자리에 건다."""
    await _buy_sixth(client, novel, reader)
    await client.post(f"{_chapter_path(novel, 7)}/purchase", json={"expectedPrice": 30})
    await client.put(
        f"{_chapter_path(novel, 7)}/reading-position",
        json={"paragraphIndex": 0, "paragraphCount": 1, "edition": 1, "finished": False},
    )
    await client.post(f"/webnovels/{novel.novel_id}/like")
    db.add(HomeNovelCuration(position=1, novel_id=novel.novel_id))
    await db.commit()


async def _reader_rows(db: AsyncSession, novel: PublicNovel) -> tuple[int | None, int | None, int | None]:
    """(읽은 자리, 좋아요, 홈 노벨 자리) 행 수."""
    count = sa.select(sa.func.count())
    return (
        await db.scalar(count.select_from(NovelReaderPosition).where(NovelReaderPosition.novel_id == novel.novel_id)),
        await db.scalar(count.select_from(NovelLike).where(NovelLike.novel_id == novel.novel_id)),
        await db.scalar(count.select_from(HomeNovelCuration).where(HomeNovelCuration.novel_id == novel.novel_id)),
    )


async def test_deleting_the_last_batch_drops_reader_positions_on_its_chapters(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel = await _novel(db_session)
    reader = await _member(db_session)
    await _plant_reader_rows(db_client, db_session, novel, reader)
    assert await _reader_rows(db_session, novel) == (1, 1, 1)
    await _allow_novelize(db_session, monkeypatch, novel.publisher_id)

    await _login_as(db_client, novel.publisher_id)
    resp = await db_client.delete(f"/novels/{novel.novel_id}/batches/{novel.batch_ids[-1]}")

    assert resp.status_code == 204
    assert await _reader_rows(db_session, novel) == (0, 1, 1)


async def test_deleting_the_novel_drops_its_reader_rows(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    novel = await _novel(db_session)
    reader = await _member(db_session)
    await _plant_reader_rows(db_client, db_session, novel, reader)

    await _login_as(db_client, novel.publisher_id)
    resp = await db_client.delete(f"/novels/{novel.novel_id}")

    assert resp.status_code == 204
    assert await _reader_rows(db_session, novel) == (0, 0, 0)


# ── 좋아요·조회 수 ──────────────────────────────────────────────────────────
async def test_like_and_unlike_move_the_count_once_each(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    novel = await _novel(db_session)
    first, second = await _member(db_session), await _member(db_session)

    await _login_as(db_client, first)
    await db_client.post(f"/webnovels/{novel.novel_id}/like")
    await db_client.post(f"/webnovels/{novel.novel_id}/like")
    await _login_as(db_client, second)
    await db_client.post(f"/webnovels/{novel.novel_id}/like")
    both = (await db_client.get(f"/webnovels/{novel.novel_id}")).json()
    await db_client.delete(f"/webnovels/{novel.novel_id}/like")
    await db_client.delete(f"/webnovels/{novel.novel_id}/like")
    after = (await db_client.get(f"/webnovels/{novel.novel_id}")).json()

    assert (both["likeCount"], both["liked"]) == (2, True)
    assert (after["likeCount"], after["liked"]) == (1, False)


async def test_views_count_once_per_reader_and_only_when_a_body_was_served(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """화 본문을 내준 때만, 소설 단위로 회원마다 한 번 센다 — 같은 사람이 여러 화를 열어도, 잠긴 화를 열어도 더 오르지 않는다.
    게시자 본인이 자기 화를 열면 세지 않는다."""
    novel = await _novel(db_session)
    reader, other = await _member(db_session), await _member(db_session)

    await _get(db_client, _chapter_path(novel, 6), as_user=reader)
    locked_only = (await db_client.get(f"/webnovels/{novel.novel_id}")).json()["viewCount"]
    await db_client.get(_chapter_path(novel, 1))
    await db_client.get(_chapter_path(novel, 2))
    await db_client.get(_chapter_path(novel, 1))
    await _get(db_client, _chapter_path(novel, 1), as_user=other)
    own = await _get(db_client, _chapter_path(novel, 1), as_user=novel.publisher_id)

    assert own.json()["access"] == "publisher"
    assert locked_only == 0
    assert (await db_client.get(f"/webnovels/{novel.novel_id}")).json()["viewCount"] == 2


# ── 목록 ────────────────────────────────────────────────────────────────────
async def test_popular_orders_by_likes_and_cursor_pages_through_without_repeats(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reading, "PUBLIC_NOVEL_LIST_PAGE_SIZE", 2)
    novels = [await _novel(db_session, batches=(1,)) for _ in range(3)]
    for novel, likes in zip(novels, (1, 3, 2), strict=True):
        await db_session.execute(
            sa.update(NovelPublication).where(NovelPublication.novel_id == novel.novel_id).values(like_count=likes)
        )
    await db_session.commit()
    reader = await _member(db_session)

    first = (await _get(db_client, "/webnovels?sort=popular", as_user=reader)).json()
    second = (await db_client.get("/webnovels", params={"sort": "popular", "cursor": first["nextCursor"]})).json()
    broken = await db_client.get("/webnovels", params={"cursor": "not-a-cursor"})

    ids = [item["id"] for item in first["items"] + second["items"]]
    assert ids == [str(novels[i].novel_id) for i in (1, 2, 0)]
    assert second["nextCursor"] is None
    assert (broken.status_code, broken.json()["detail"]) == (422, {"code": "INVALID_CURSOR"})


async def test_latest_orders_by_last_publish_time(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    older, newer = await _novel(db_session, batches=(1,)), await _novel(db_session, batches=(1,))
    await db_session.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == older.novel_id)
        .values(published_at=sa.func.now() - sa.text("interval '1 day'"))
    )
    await db_session.commit()
    reader = await _member(db_session)

    items = (await _get(db_client, "/webnovels", as_user=reader)).json()["items"]

    assert [item["id"] for item in items] == [str(newer.novel_id), str(older.novel_id)]
    assert (items[0]["chapterCount"], items[0]["title"]) == (1, "공개 제목")


# ── 스위치 ──────────────────────────────────────────────────────────────────
async def test_switch_off_hides_every_reader_route_and_the_public_flag_says_so(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    novel = await _novel(db_session)
    reader = await _member(db_session)
    await _login_as(db_client, reader)
    assert (await db_client.get("/clover/pricing")).json()["novelPublicEnabled"] is True

    settings.novel_public_enabled = False
    responses = [
        await db_client.get("/webnovels"),
        await db_client.get("/webnovels/home-curation"),
        await db_client.get(f"/webnovels/{novel.novel_id}"),
        await db_client.get(_chapter_path(novel, 1)),
        await db_client.post(f"/webnovels/{novel.novel_id}/like"),
        await db_client.put(
            f"{_chapter_path(novel, 1)}/reading-position",
            json={"paragraphIndex": 0, "paragraphCount": 1, "edition": 1, "finished": False},
        ),
    ]
    db_client.cookies.clear()
    pricing = await db_client.get("/clover/pricing")

    assert [r.status_code for r in responses] == [404] * 6
    assert pricing.json()["novelPublicEnabled"] is False


async def test_reader_routes_need_login(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    novel = await _novel(db_session)

    assert (await db_client.get("/webnovels")).status_code == 401
    assert (await db_client.get(_chapter_path(novel, 1))).status_code == 401


# ── 홈 노벨 ─────────────────────────────────────────────────────────────────
async def _as_admin(client: httpx.AsyncClient, db: AsyncSession) -> None:
    admin = await _create_admin(db)
    await db.commit()
    await _login_as_admin(client, admin)


async def test_admin_curates_home_novels_and_home_shows_only_readable_ones_in_slot_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """자리 순으로 보인다. 걸린 노벨이 이용제한되면 지정은 남은 채 홈에서 빠지고, 이용제한 중인 노벨은 새로 걸 수 없다.
    같은 노벨을 다른 자리에 걸면 옮겨진다. 지정·해제는 노벨을 대상으로 감사 로그에 남는다."""
    first, second, third = [await _novel(db_session, batches=(1,)) for _ in range(3)]
    await _as_admin(db_client, db_session)
    assert (await db_client.put("/admin/home-novel-curations/2", json={"novelId": str(first.novel_id)})).status_code == 204
    assert (await db_client.put("/admin/home-novel-curations/1", json={"novelId": str(second.novel_id)})).status_code == 204
    assert (await db_client.put("/admin/home-novel-curations/3", json={"novelId": str(first.novel_id)})).status_code == 204
    await _restrict(db_session, third)
    await db_session.commit()
    rejected = await db_client.put("/admin/home-novel-curations/4", json={"novelId": str(third.novel_id)})
    out_of_range = await db_client.put("/admin/home-novel-curations/11", json={"novelId": str(first.novel_id)})
    slots = (await db_client.get("/admin/home-novel-curations")).json()["items"]

    reader = await _member(db_session)
    home = (await _get(db_client, "/webnovels/home-curation", as_user=reader)).json()["items"]
    await _restrict(db_session, second)
    await db_session.commit()
    after_restrict = (await db_client.get("/webnovels/home-curation")).json()["items"]

    assert (rejected.status_code, rejected.json()["detail"]) == (400, {"code": "NOT_PUBLICLY_LISTED"})
    assert out_of_range.status_code == 422
    assert [(s["position"], s["novel"]["id"] if s["novel"] else None) for s in slots[:4]] == [
        (1, str(second.novel_id)),
        (2, None),
        (3, str(first.novel_id)),
        (4, None),
    ]
    assert len(slots) == 10
    assert [item["id"] for item in home] == [str(second.novel_id), str(first.novel_id)]
    assert [item["id"] for item in after_restrict] == [str(first.novel_id)]
    logs = (
        await db_session.execute(
            sa.select(AdminActionLog.action_type, AdminActionLog.target_novel_id).order_by(AdminActionLog.created_at)
        )
    ).all()
    assert sorted(logs) == sorted(
        [
            ("home-novel-curation-set", first.novel_id),
            ("home-novel-curation-set", second.novel_id),
            ("home-novel-curation-set", first.novel_id),
        ]
    )


async def test_a_novel_deleted_while_being_curated_is_a_conflict_not_a_server_error(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """읽을 수 있다고 판정한 뒤 지정을 쓰기 전에 게시자가 소설을 지우면 409 이고, 자리는 비어 있고 감사 로그도 남지 않는다."""
    novel = await _novel(db_session, batches=(1,))
    await _as_admin(db_client, db_session)
    listed = home_novel_curation._is_listed

    async def deleted_right_after_the_check(db: AsyncSession, novel_id: uuid.UUID) -> bool:
        readable = await listed(db, novel_id)
        await delete_novels(db, [novel_id])
        return readable

    monkeypatch.setattr(home_novel_curation, "_is_listed", deleted_right_after_the_check)

    resp = await db_client.put("/admin/home-novel-curations/1", json={"novelId": str(novel.novel_id)})

    assert (resp.status_code, resp.json()["detail"]) == (409, {"code": "HOME_NOVEL_CURATION_CONFLICT"})
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(HomeNovelCuration)) == 0
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(AdminActionLog)) == 0


async def test_admin_clears_a_home_novel_slot(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    novel = await _novel(db_session, batches=(1,))
    db_session.add(HomeNovelCuration(position=1, novel_id=novel.novel_id))
    await db_session.commit()
    await _as_admin(db_client, db_session)

    cleared = await db_client.delete("/admin/home-novel-curations/1")
    again = await db_client.delete("/admin/home-novel-curations/1")

    assert (cleared.status_code, again.status_code) == (204, 204)
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(HomeNovelCuration)) == 0
    logs = (await db_session.execute(sa.select(AdminActionLog.action_type, AdminActionLog.target_novel_id))).tuples()
    assert list(logs) == [("home-novel-curation-clear", novel.novel_id)]


async def test_home_novel_admin_routes_need_an_admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    member = await _member(db_session)
    await _login_as(db_client, member)

    assert (await db_client.get("/admin/home-novel-curations")).status_code == 401
    assert (await db_client.delete("/admin/home-novel-curations/1")).status_code == 401
