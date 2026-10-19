"""노벨 화의 판 고르기 — 산 사람은 기본으로 지금 판을 읽고, 산 때의 판을 골라 다시 읽을 수 있다.

공개 소설은 `_make_public_novel`(원작 = 다른 회원의 공개 작품, 6화 + 2화 묶음, 전부 공개)로 만든다. 앞 5화가 무료라 6화가
첫 유료 화이고, 본문은 "n화 본문" 이다. 다시 공개는 라우트(글 심사)를 거치지 않고 DB 에서 흉내 낸다(`_republish`) — 새
개정을 만들고 화 공개본을 그 개정으로 덮어 판을 올리며, 지난 판과 새 판의 판 행을 남긴다. 다시 공개 라우트가 판 행을 쌓는
것은 공개 라우트 테스트가 따로 본다."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.novel import NovelChapterEdition, NovelChapterPublication, NovelChapterRevision
from factories import PublicNovel, _login_as, _make_public_novel, _make_user, _make_user_with_clover_lot


@pytest.fixture(autouse=True)
def _novel_public_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_public_enabled", True)
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", True)


async def _member(db_session: AsyncSession, balance: int = 100) -> uuid.UUID:
    user = await _make_user_with_clover_lot(db_session, clover_balance=balance)
    await db_session.commit()
    return user.id


async def _novel(db_session: AsyncSession) -> PublicNovel:
    publisher = _make_user()
    db_session.add(publisher)
    await db_session.flush()
    novel = await _make_public_novel(db_session, publisher.id)
    await db_session.commit()
    return novel


def _path(novel: PublicNovel, ordinal: int) -> str:
    return f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[ordinal - 1]}"


async def _read(
    client: httpx.AsyncClient, novel: PublicNovel, ordinal: int, *, as_user: uuid.UUID, edition: int | None = None
) -> httpx.Response:
    await _login_as(client, as_user)
    params = {"edition": edition} if edition is not None else None
    return await client.get(_path(novel, ordinal), params=params)


async def _buy(client: httpx.AsyncClient, novel: PublicNovel, ordinal: int, buyer: uuid.UUID) -> None:
    await _login_as(client, buyer)
    resp = await client.post(f"{_path(novel, ordinal)}/purchase", json={"expectedPrice": 30})
    assert resp.status_code == 200, resp.text


async def _edition_row(db_session: AsyncSession, publication: NovelChapterPublication) -> None:
    """화 공개본의 지금 판을 판 행으로 남긴다(이미 있으면 그대로)."""
    await db_session.execute(
        insert(NovelChapterEdition)
        .values(
            chapter_id=publication.chapter_id,
            edition=publication.edition,
            novel_id=publication.novel_id,
            revision_id=publication.revision_id,
            title=publication.title,
            author_note=publication.author_note,
            published_at=publication.published_at,
        )
        .on_conflict_do_nothing()
    )


async def _republish(
    db_session: AsyncSession, novel: PublicNovel, ordinal: int, *, body: str, title: str, note: str, at: datetime
) -> NovelChapterPublication:
    """그 화를 새 본문·제목·작가의 말로 다시 공개한 것처럼 만들고 새 화 공개본을 돌려준다."""
    chapter_id = novel.chapter_ids[ordinal - 1]
    before = await db_session.get_one(NovelChapterPublication, chapter_id, populate_existing=True)
    await _edition_row(db_session, before)
    latest = await db_session.scalar(
        sa.select(sa.func.max(NovelChapterRevision.revision_no)).where(NovelChapterRevision.chapter_id == chapter_id)
    )
    revision = NovelChapterRevision(chapter_id=chapter_id, revision_no=(latest or 0) + 1, body=body, source="manual_edit")
    db_session.add(revision)
    await db_session.flush()
    await db_session.execute(
        sa.update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == chapter_id)
        .values(
            revision_id=revision.id,
            title=title,
            author_note=note,
            edition=NovelChapterPublication.edition + 1,
            published_at=at,
        )
    )
    after = await db_session.get_one(NovelChapterPublication, chapter_id, populate_existing=True)
    await _edition_row(db_session, after)
    await db_session.commit()
    return after


async def _first_published_at(db_session: AsyncSession, novel: PublicNovel, ordinal: int) -> datetime:
    publication = await db_session.get_one(
        NovelChapterPublication, novel.chapter_ids[ordinal - 1], populate_existing=True
    )
    return publication.published_at


def _purchased_edition(body: dict[str, object]) -> tuple[object, datetime] | None:
    value = body.get("purchasedEdition")
    if value is None:
        return None
    assert isinstance(value, dict)
    return value["edition"], datetime.fromisoformat(value["publishedAt"])


async def test_a_buyer_reads_the_latest_edition_by_default_and_can_pick_the_one_bought(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """6화를 1판일 때 산 사람은, 작가가 고쳐 2판을 낸 뒤에도 기본으로 2판(새 본문·제목·작가의 말)을 읽고, 응답이 산 때의
    판 번호와 그 판의 공개 시각을 알려 준다. 1판을 고르면 1판의 본문·제목·작가의 말을 읽는다. 깨지는 시나리오: 다시 공개가
    판을 덮어 산 사람이 산 글을 다시 볼 수 없거나, 고른 판의 제목·작가의 말이 지금 판 것으로 섞인다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _buy(db_client, novel, 6, buyer)
    bought_at = await _first_published_at(db_session, novel, 6)
    await _republish(
        db_session, novel, 6, body="고친 6화 본문", title="고친 제목", note="고친 작가의 말", at=bought_at + timedelta(days=3)
    )

    latest = await _read(db_client, novel, 6, as_user=buyer)
    bought = await _read(db_client, novel, 6, as_user=buyer, edition=1)

    assert latest.status_code == 200, latest.text
    body = latest.json()
    assert (body["edition"], body["paragraphs"], body["title"], body["authorNote"]) == (
        2,
        ["고친 6화 본문"],
        "고친 제목",
        "고친 작가의 말",
    )
    assert _purchased_edition(body) == (1, bought_at)
    assert bought.status_code == 200, bought.text
    old = bought.json()
    assert (old["edition"], old["paragraphs"], old["title"], old["authorNote"]) == (1, ["6화 본문"], None, "")
    assert _purchased_edition(old) == (1, bought_at)


async def test_only_the_current_edition_is_open_to_anyone_who_did_not_buy_that_chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """지금 판 아닌 판은 그 화를 산 사람만 고른다 — 사지 않은 독자, 무료 화의 독자(산 사람 포함), 게시자 본인은 지난 판을
    고르면 404 이고 지금 판은 그대로 열린다. 깨지는 시나리오: 판 번호만 바꿔 남의 구매 당시 글이나 작가가 고쳐 내린 지난
    글이 누구에게나 다시 나간다."""
    novel = await _novel(db_session)
    buyer, stranger = await _member(db_session), await _member(db_session)
    await _buy(db_client, novel, 6, buyer)
    at = datetime.now(UTC) + timedelta(days=1)
    await _republish(db_session, novel, 6, body="고친 6화", title="6", note="", at=at)
    await _republish(db_session, novel, 1, body="고친 1화", title="1", note="", at=at)

    refused = [
        await _read(db_client, novel, 6, as_user=stranger, edition=1),
        await _read(db_client, novel, 1, as_user=stranger, edition=1),
        await _read(db_client, novel, 1, as_user=buyer, edition=1),
        await _read(db_client, novel, 6, as_user=novel.publisher_id, edition=1),
    ]
    current = await _read(db_client, novel, 6, as_user=stranger, edition=2)

    assert [resp.status_code for resp in refused] == [404, 404, 404, 404]
    assert (current.status_code, current.json()["edition"], current.json()["access"]) == (200, 2, "locked")


async def test_a_buyer_from_before_edition_history_gets_the_oldest_kept_edition(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """판 이력이 생기기 전에 1판을 산 사람 — 그 뒤 판 이력이 2판부터 남았다(1판 행이 없다). 산 때의 판은 남아 있는 가장
    오래된 판(2판)으로 대신하고, 그 판을 고르면 그 본문을 읽는다. 깨지는 시나리오: 산 때의 판 행이 없다고 판 고르기가
    사라지거나 500 이 되고, 지금 판(3판)을 산 때의 판으로 알려 준다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _buy(db_client, novel, 6, buyer)
    second_at = datetime.now(UTC) + timedelta(days=1)
    await _republish(db_session, novel, 6, body="2판 본문", title="2판", note="", at=second_at)
    await db_session.execute(
        sa.delete(NovelChapterEdition).where(
            NovelChapterEdition.chapter_id == novel.chapter_ids[5], NovelChapterEdition.edition == 1
        )
    )
    await db_session.commit()
    await _republish(db_session, novel, 6, body="3판 본문", title="3판", note="", at=second_at + timedelta(days=1))

    latest = await _read(db_client, novel, 6, as_user=buyer)
    substitute = await _read(db_client, novel, 6, as_user=buyer, edition=2)

    assert latest.status_code == 200, latest.text
    assert latest.json()["edition"] == 3
    assert _purchased_edition(latest.json()) == (2, second_at)
    assert substitute.status_code == 200, substitute.text
    assert (substitute.json()["edition"], substitute.json()["paragraphs"]) == (2, ["2판 본문"])


async def test_with_the_policy_switch_off_picking_an_edition_still_serves_the_current_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정책 스위치가 꺼져 있으면 지금 동작 그대로다 — 판을 골라도 지금 판을 주고 산 때의 판을 알리지 않는다. 깨지는 시나리오:
    약관 개정 전에 판 고르기가 먼저 열린다."""
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", False)
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _buy(db_client, novel, 6, buyer)
    await _republish(db_session, novel, 6, body="고친 6화", title="6", note="", at=datetime.now(UTC) + timedelta(days=1))

    resp = await _read(db_client, novel, 6, as_user=buyer, edition=1)

    assert resp.status_code == 200, resp.text
    assert (resp.json()["edition"], resp.json()["paragraphs"]) == (2, ["고친 6화"])
    assert _purchased_edition(resp.json()) is None
