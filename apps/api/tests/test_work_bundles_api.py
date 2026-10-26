"""작품 묶음(`/me/work-bundles`) — 작가가 자기 작품·소설을 사적으로 정리하는 묶음.

묶음은 소유자에게만 있다(남의 묶음·남의 작품은 모두 404). 묶음을 지워도 작품은 그대로이고, 작품·소설이 하드 삭제되면 소속
행만 DB 가 지운다. 탈퇴는 회원 행을 지우지 않으므로 FK CASCADE 가 돌지 않아 탈퇴 파기가 묶음을 직접 지운다. 소속 표의 "정확히
하나" CHECK 와 묶음 안 중복을 막는 부분 유니크는 `alembic check` 가 비교하지 않아 여기서 `IntegrityError` 로 지킨다."""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.chat import ChatRoom
from api.db.models.content import Content, ModerationStatus
from api.db.models.feature_grant import UserFeatureGrant
from api.db.models.novel import Novel
from api.db.models.work_bundle import WorkBundle, WorkBundleItem
from factories import (
    _allow_novelize,
    _get_genre,
    _login_as,
    _make_draft_content,
    _make_published_character,
    _make_user,
)

_OLD = datetime(2026, 1, 1, tzinfo=UTC)


async def _member(db_client: httpx.AsyncClient, db_session: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user.id


async def _other_user(db_session: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    return user.id


async def _draft(db_client: httpx.AsyncClient, kind: str = "character") -> uuid.UUID:
    """로그인한 회원의 초안 하나를 실제 생성 경로로 만든다(목록에 나오려면 상세 행이 있어야 한다)."""
    resp = await db_client.post("/contents", json={"type": kind})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["contentId"])


async def _novel(db_session: AsyncSession, owner_id: uuid.UUID, *, hidden: bool = False) -> uuid.UUID:
    novel = Novel(
        user_id=owner_id,
        content_id=uuid.uuid4(),
        content_type="character",
        content_title="원작",
        character_name="인물",
        hidden_at=datetime.now(UTC) if hidden else None,
    )
    db_session.add(novel)
    await db_session.flush()
    return novel.id


async def _bundle(db_client: httpx.AsyncClient, name: str = "묶음") -> uuid.UUID:
    resp = await db_client.post("/me/work-bundles", json={"name": name})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _bundles(db_client: httpx.AsyncClient, **params: str) -> list[dict[str, Any]]:
    resp = await db_client.get("/me/work-bundles", params=params)
    assert resp.status_code == 200, resp.text
    items: list[dict[str, Any]] = resp.json()["items"]
    return items


async def _put(db_client: httpx.AsyncClient, bundle_id: uuid.UUID, kind: str, work_id: uuid.UUID) -> httpx.Response:
    return await db_client.put(f"/me/work-bundles/{bundle_id}/items/{kind}/{work_id}")


async def _listed_ids(db_client: httpx.AsyncClient, bundle_id: uuid.UUID) -> set[str]:
    resp = await db_client.get("/me/works", params={"bundleId": str(bundle_id)})
    assert resp.status_code == 200, resp.text
    return {item["id"] for item in resp.json()["items"]}


async def _item_rows(db_session: AsyncSession, bundle_id: uuid.UUID) -> list[tuple[uuid.UUID | None, uuid.UUID | None]]:
    rows = await db_session.execute(
        sa.select(WorkBundleItem.content_id, WorkBundleItem.novel_id).where(WorkBundleItem.bundle_id == bundle_id)
    )
    return [(content_id, novel_id) for content_id, novel_id in rows.all()]


# ── 표 제약(`alembic check` 가 비교하지 않는 것) ─────────────────────────────


async def _raw_bundle(db_session: AsyncSession) -> uuid.UUID:
    owner_id = await _other_user(db_session)
    bundle = WorkBundle(owner_user_id=owner_id, name="묶음")
    db_session.add(bundle)
    await db_session.flush()
    return bundle.id


@pytest.mark.parametrize("both", [pytest.param(False, id="neither"), pytest.param(True, id="both")])
async def test_a_bundle_item_must_point_at_exactly_one_work(db_session: AsyncSession, both: bool) -> None:
    bundle_id = await _raw_bundle(db_session)
    owner_id = await _other_user(db_session)
    content = await _make_draft_content(db_session, creator_user_id=owner_id)
    novel_id = await _novel(db_session, owner_id)

    db_session.add(
        WorkBundleItem(bundle_id=bundle_id, content_id=content.id if both else None, novel_id=novel_id if both else None)
    )
    with pytest.raises(IntegrityError, match="ck_work_bundle_items_exactly_one_work"):
        await db_session.flush()


async def test_the_same_work_goes_once_per_bundle_but_into_any_number_of_bundles(db_session: AsyncSession) -> None:
    """부분 유니크가 막는 쪽(한 묶음 안 중복)과 막지 않는 쪽(다른 묶음)을 작품·소설 모두에서 본다."""
    first = await _raw_bundle(db_session)
    second = await _raw_bundle(db_session)
    owner_id = await _other_user(db_session)
    content = await _make_draft_content(db_session, creator_user_id=owner_id)
    novel_id = await _novel(db_session, owner_id)

    db_session.add_all(
        [
            WorkBundleItem(bundle_id=first, content_id=content.id),
            WorkBundleItem(bundle_id=second, content_id=content.id),
            WorkBundleItem(bundle_id=first, novel_id=novel_id),
            WorkBundleItem(bundle_id=second, novel_id=novel_id),
        ]
    )
    await db_session.flush()

    async with db_session.begin_nested():
        db_session.add(WorkBundleItem(bundle_id=first, content_id=content.id))
        with pytest.raises(IntegrityError, match="ux_work_bundle_items_content_id_bundle_id"):
            await db_session.flush()
    async with db_session.begin_nested():
        db_session.add(WorkBundleItem(bundle_id=first, novel_id=novel_id))
        with pytest.raises(IntegrityError, match="ux_work_bundle_items_novel_id_bundle_id"):
            await db_session.flush()


# ── 만들기·이름 바꾸기·지우기 ─────────────────────────────────────────────────


async def test_bundles_need_a_login(db_client: httpx.AsyncClient) -> None:
    assert (await db_client.get("/me/work-bundles")).status_code == 401
    assert (await db_client.post("/me/work-bundles", json={"name": "묶음"})).status_code == 401


async def test_creating_renaming_and_deleting_a_bundle(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _member(db_client, db_session)
    bundle_id = await _bundle(db_client, "  여름 작품  ")
    listed = await _bundles(db_client)
    assert [{k: v for k, v in b.items() if k != "updatedAt"} for b in listed] == [
        {"id": str(bundle_id), "name": "여름 작품", "itemCount": 0, "containsWork": None}
    ]

    resp = await db_client.patch(f"/me/work-bundles/{bundle_id}", json={"name": "가을 작품"})
    assert resp.status_code == 204, resp.text
    assert [b["name"] for b in await _bundles(db_client)] == ["가을 작품"]

    resp = await db_client.delete(f"/me/work-bundles/{bundle_id}")
    assert resp.status_code == 204, resp.text
    assert await _bundles(db_client) == []


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        pytest.param("가" * 40, True, id="40"),
        pytest.param(" " + "가" * 40 + " ", True, id="40-trimmed"),
        pytest.param("가" * 41, False, id="41"),
        pytest.param("   ", False, id="blank"),
    ],
)
async def test_bundle_names_are_trimmed_and_capped_at_forty(
    db_client: httpx.AsyncClient, db_session: AsyncSession, name: str, ok: bool
) -> None:
    await _member(db_client, db_session)
    resp = await db_client.post("/me/work-bundles", json={"name": name})
    assert resp.status_code == (201 if ok else 422), resp.text
    bundle_id = await _bundle(db_client)
    resp = await db_client.patch(f"/me/work-bundles/{bundle_id}", json={"name": name})
    assert resp.status_code == (204 if ok else 422), resp.text


async def test_bundles_list_most_recently_changed_first(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """이름 바꾸기·넣기·빼기가 묶음을 앞으로 당긴다. 같은 이름도 허용한다."""
    await _member(db_client, db_session)
    first = await _bundle(db_client, "같은 이름")
    second = await _bundle(db_client, "같은 이름")
    content_id = await _draft(db_client)

    async def order() -> list[str]:
        return [b["id"] for b in await _bundles(db_client)]

    async def age_all() -> None:
        await db_session.execute(
            sa.update(WorkBundle).where(WorkBundle.id.in_([first, second])).values(updated_at=_OLD)
        )
        await db_session.execute(sa.update(WorkBundle).where(WorkBundle.id == second).values(updated_at=_OLD.replace(day=2)))
        await db_session.commit()

    await age_all()
    assert await order() == [str(second), str(first)]
    assert (await db_client.patch(f"/me/work-bundles/{first}", json={"name": "새 이름"})).status_code == 204
    assert await order() == [str(first), str(second)]

    await age_all()
    assert (await _put(db_client, first, "character", content_id)).status_code == 204
    assert await order() == [str(first), str(second)]

    await age_all()
    resp = await db_client.delete(f"/me/work-bundles/{first}/items/character/{content_id}")
    assert resp.status_code == 204
    assert await order() == [str(first), str(second)]


async def test_a_member_has_at_most_the_bundle_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.works import bundles

    monkeypatch.setattr(bundles, "MAX_BUNDLES_PER_USER", 2)
    await _member(db_client, db_session)
    await _bundle(db_client)
    await _bundle(db_client)
    resp = await db_client.post("/me/work-bundles", json={"name": "셋째"})
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "WORK_BUNDLE_LIMIT"}
    assert len(await _bundles(db_client)) == 2


async def test_a_bundle_holds_at_most_the_item_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.works import bundles

    monkeypatch.setattr(bundles, "MAX_ITEMS_PER_BUNDLE", 2)
    await _member(db_client, db_session)
    bundle_id = await _bundle(db_client)
    works = [await _draft(db_client) for _ in range(3)]
    assert (await _put(db_client, bundle_id, "character", works[0])).status_code == 204
    assert (await _put(db_client, bundle_id, "character", works[1])).status_code == 204
    # 이미 든 작품을 다시 넣는 것은 한도에 걸리지 않는다(멱등).
    assert (await _put(db_client, bundle_id, "character", works[1])).status_code == 204
    resp = await _put(db_client, bundle_id, "character", works[2])
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "WORK_BUNDLE_LIMIT"}
    assert len(await _item_rows(db_session, bundle_id)) == 2


async def test_bundle_writes_need_current_consent_but_deleting_does_not(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """만들기·이름 바꾸기·넣기는 재동의 전에 막고, 지우기·빼기(자기 데이터 정리)는 연다."""
    user_id = await _member(db_client, db_session)
    bundle_id = await _bundle(db_client)
    content_id = await _draft(db_client)
    assert (await _put(db_client, bundle_id, "character", content_id)).status_code == 204
    await db_session.execute(sa.text("UPDATE users SET terms_version = NULL WHERE id = :id"), {"id": user_id})
    await db_session.commit()

    for resp in (
        await db_client.post("/me/work-bundles", json={"name": "묶음"}),
        await db_client.patch(f"/me/work-bundles/{bundle_id}", json={"name": "새 이름"}),
        await _put(db_client, bundle_id, "story", content_id),
    ):
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["code"] == "LEGAL_RECONSENT_REQUIRED"
    assert (await db_client.delete(f"/me/work-bundles/{bundle_id}/items/character/{content_id}")).status_code == 204
    assert (await db_client.delete(f"/me/work-bundles/{bundle_id}")).status_code == 204


# ── 넣기·빼기와 소유 검사 ────────────────────────────────────────────────────


async def test_putting_and_removing_works(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _member(db_client, db_session)
    await _allow_novelize(db_session, monkeypatch, user_id)
    bundle_id = await _bundle(db_client)
    character_id = await _draft(db_client, "character")
    story_id = await _draft(db_client, "story")
    novel_id = await _novel(db_session, user_id)
    await db_session.commit()

    for kind, work_id in (("character", character_id), ("story", story_id), ("novel", novel_id)):
        assert (await _put(db_client, bundle_id, kind, work_id)).status_code == 204
        assert (await _put(db_client, bundle_id, kind, work_id)).status_code == 204  # 멱등
    assert await _listed_ids(db_client, bundle_id) == {str(character_id), str(story_id), str(novel_id)}
    assert len(await _item_rows(db_session, bundle_id)) == 3

    assert (await db_client.delete(f"/me/work-bundles/{bundle_id}/items/novel/{novel_id}")).status_code == 204
    assert (await db_client.delete(f"/me/work-bundles/{bundle_id}/items/novel/{novel_id}")).status_code == 204
    assert await _listed_ids(db_client, bundle_id) == {str(character_id), str(story_id)}


@pytest.mark.parametrize(
    ("kind", "wrong_kind"), [pytest.param("character", "story", id="character"), pytest.param("story", "character", id="story")]
)
async def test_a_work_goes_in_only_under_its_own_kind(
    db_client: httpx.AsyncClient, db_session: AsyncSession, kind: str, wrong_kind: str
) -> None:
    await _member(db_client, db_session)
    bundle_id = await _bundle(db_client)
    content_id = await _draft(db_client, kind)
    resp = await _put(db_client, bundle_id, wrong_kind, content_id)
    assert resp.status_code == 404
    assert resp.json()["detail"] == {"code": "WORK_NOT_FOUND"}
    assert (await _put(db_client, bundle_id, kind, content_id)).status_code == 204


async def test_someone_elses_bundle_is_not_found_for_every_route(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """남의 묶음은 읽기·이름 바꾸기·지우기·넣기·빼기 모두 404 이고, 남의 묶음은 그대로다."""
    owner_id = await _member(db_client, db_session)
    theirs = await _bundle(db_client, "남의 묶음")
    their_work = await _draft(db_client)
    assert (await _put(db_client, theirs, "character", their_work)).status_code == 204

    await _member(db_client, db_session)
    my_work = await _draft(db_client)
    missing = uuid.uuid4()
    for bundle_id in (theirs, missing):
        for resp in (
            await db_client.get("/me/works", params={"bundleId": str(bundle_id)}),
            await db_client.patch(f"/me/work-bundles/{bundle_id}", json={"name": "가로채기"}),
            await db_client.delete(f"/me/work-bundles/{bundle_id}"),
            await _put(db_client, bundle_id, "character", my_work),
            await db_client.delete(f"/me/work-bundles/{bundle_id}/items/character/{their_work}"),
        ):
            assert resp.status_code == 404, resp.text
            assert resp.json()["detail"] == {"code": "WORK_BUNDLE_NOT_FOUND"}
    assert await _bundles(db_client) == []

    bundle = await db_session.get(WorkBundle, theirs, populate_existing=True)
    assert bundle is not None and bundle.name == "남의 묶음" and bundle.owner_user_id == owner_id
    assert await _item_rows(db_session, theirs) == [(their_work, None)]


async def test_someone_elses_work_cannot_go_into_my_bundle(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """남의 작품·남의 소설, 내 것이라도 운영 삭제된 작품·숨긴 소설은 넣지 못한다(404, 행 없음). 같은 셋업의 내 작품·내 소설은
    들어간다."""
    other_id = await _member(db_client, db_session)
    their_content = await _draft(db_client)
    their_novel = await _novel(db_session, other_id)

    user_id = await _member(db_client, db_session)
    await _allow_novelize(db_session, monkeypatch, user_id)
    bundle_id = await _bundle(db_client)
    my_content = await _draft(db_client)
    deleted_content = await _draft(db_client)
    await db_session.execute(
        sa.update(Content).where(Content.id == deleted_content).values(moderation_status=ModerationStatus.DELETED)
    )
    my_novel = await _novel(db_session, user_id)
    hidden_novel = await _novel(db_session, user_id, hidden=True)
    await db_session.commit()

    for kind, work_id in (
        ("character", their_content),
        ("novel", their_novel),
        ("character", deleted_content),
        ("novel", hidden_novel),
        ("character", uuid.uuid4()),
        ("novel", uuid.uuid4()),
    ):
        resp = await _put(db_client, bundle_id, kind, work_id)
        assert resp.status_code == 404, (kind, work_id, resp.text)
        assert resp.json()["detail"] == {"code": "WORK_NOT_FOUND"}
    assert await _item_rows(db_session, bundle_id) == []

    assert (await _put(db_client, bundle_id, "character", my_content)).status_code == 204
    assert (await _put(db_client, bundle_id, "novel", my_novel)).status_code == 204


@pytest.mark.parametrize("allowed", [pytest.param(True, id="allowed"), pytest.param(False, id="not-allowed")])
async def test_novels_go_into_bundles_only_for_accounts_allowed_to_novelize(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, allowed: bool
) -> None:
    user_id = await _member(db_client, db_session)
    if allowed:
        await _allow_novelize(db_session, monkeypatch, user_id)
    bundle_id = await _bundle(db_client)
    novel_id = await _novel(db_session, user_id)
    await db_session.commit()

    resp = await _put(db_client, bundle_id, "novel", novel_id)
    assert resp.status_code == (204 if allowed else 404), resp.text
    assert await _item_rows(db_session, bundle_id) == ([(None, novel_id)] if allowed else [])


# ── 항목 수·체크 표시 ─────────────────────────────────────────────────────────


async def test_item_count_counts_exactly_what_the_bundle_list_shows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """넣은 뒤 운영 삭제된 작품·숨긴 소설은 소속 행이 남아도 항목 수와 묶음 목록 모두에서 빠지고, 소설화 허용을 잃으면
    소설이 둘 모두에서 빠진다."""
    user_id = await _member(db_client, db_session)
    await _allow_novelize(db_session, monkeypatch, user_id)
    bundle_id = await _bundle(db_client)
    other_bundle = await _bundle(db_client)
    kept = await _draft(db_client)
    removed = await _draft(db_client)
    novel_id = await _novel(db_session, user_id)
    hidden_later = await _novel(db_session, user_id)
    await db_session.commit()
    for kind, work_id in (
        ("character", kept),
        ("character", removed),
        ("novel", novel_id),
        ("novel", hidden_later),
    ):
        assert (await _put(db_client, bundle_id, kind, work_id)).status_code == 204
    assert (await _put(db_client, other_bundle, "character", kept)).status_code == 204

    async def counts() -> dict[str, int]:
        return {b["id"]: b["itemCount"] for b in await _bundles(db_client)}

    assert await counts() == {str(bundle_id): 4, str(other_bundle): 1}
    assert len(await _listed_ids(db_client, bundle_id)) == 4

    await db_session.execute(
        sa.update(Content).where(Content.id == removed).values(moderation_status=ModerationStatus.DELETED)
    )
    await db_session.execute(sa.update(Novel).where(Novel.id == hidden_later).values(hidden_at=datetime.now(UTC)))
    await db_session.commit()
    assert await counts() == {str(bundle_id): 2, str(other_bundle): 1}
    assert await _listed_ids(db_client, bundle_id) == {str(kept), str(novel_id)}
    assert len(await _item_rows(db_session, bundle_id)) == 4

    await db_session.execute(sa.delete(UserFeatureGrant).where(UserFeatureGrant.user_id == user_id))
    await db_session.commit()
    assert await counts() == {str(bundle_id): 1, str(other_bundle): 1}
    assert await _listed_ids(db_client, bundle_id) == {str(kept)}


async def test_contains_work_marks_the_bundles_holding_that_work(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _member(db_client, db_session)
    holding = await _bundle(db_client)
    empty = await _bundle(db_client)
    content_id = await _draft(db_client)
    assert (await _put(db_client, holding, "character", content_id)).status_code == 204

    marks = {
        b["id"]: b["containsWork"] for b in await _bundles(db_client, kind="character", workId=str(content_id))
    }
    assert marks == {str(holding): True, str(empty): False}
    assert {b["containsWork"] for b in await _bundles(db_client)} == {None}
    # 같은 id 라도 소설로 물으면 작품 소속이 아니다.
    marks = {b["id"]: b["containsWork"] for b in await _bundles(db_client, kind="novel", workId=str(content_id))}
    assert marks == {str(holding): False, str(empty): False}
    assert (await db_client.get("/me/work-bundles", params={"kind": "character"})).status_code == 422


# ── 지우기 경로 ──────────────────────────────────────────────────────────────


async def test_deleting_a_bundle_leaves_works_novels_and_chats(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _member(db_client, db_session)
    await _allow_novelize(db_session, monkeypatch, user_id)
    genre = await _get_genre(db_session)
    published = await _make_published_character(db_session, creator_user_id=user_id, genre_id=genre.id)
    room = ChatRoom(user_id=user_id, content_id=published.id, content_version_id=published.current_published_version_id)
    db_session.add(room)
    await db_session.flush()
    novel_id = await _novel(db_session, user_id)
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(chat_room_id=room.id))
    await db_session.commit()
    draft_id = await _draft(db_client)
    bundle_id = await _bundle(db_client)
    for kind, work_id in (("character", published.id), ("character", draft_id), ("novel", novel_id)):
        assert (await _put(db_client, bundle_id, kind, work_id)).status_code == 204

    assert (await db_client.delete(f"/me/work-bundles/{bundle_id}")).status_code == 204

    assert await _item_rows(db_session, bundle_id) == []
    for model, row_id in ((Content, published.id), (Content, draft_id), (Novel, novel_id), (ChatRoom, room.id)):
        assert await db_session.scalar(sa.select(model.id).where(model.id == row_id)) == row_id


async def test_deleting_a_draft_removes_only_its_bundle_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _member(db_client, db_session)
    first = await _bundle(db_client)
    second = await _bundle(db_client)
    doomed = await _draft(db_client)
    kept = await _draft(db_client)
    for bundle_id in (first, second):
        assert (await _put(db_client, bundle_id, "character", doomed)).status_code == 204
    assert (await _put(db_client, first, "character", kept)).status_code == 204

    assert (await db_client.delete(f"/contents/{doomed}/draft")).status_code == 204

    assert await _item_rows(db_session, first) == [(kept, None)]
    assert await _item_rows(db_session, second) == []
    assert {b["id"] for b in await _bundles(db_client)} == {str(first), str(second)}


async def test_deleting_a_novel_removes_only_its_bundle_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _member(db_client, db_session)
    await _allow_novelize(db_session, monkeypatch, user_id)
    bundle_id = await _bundle(db_client)
    doomed = await _novel(db_session, user_id)
    kept = await _novel(db_session, user_id)
    await db_session.commit()
    for novel_id in (doomed, kept):
        assert (await _put(db_client, bundle_id, "novel", novel_id)).status_code == 204

    assert (await db_client.delete(f"/novels/{doomed}")).status_code == 204

    assert await _item_rows(db_session, bundle_id) == [(None, kept)]
    assert [b["id"] for b in await _bundles(db_client)] == [str(bundle_id)]


async def test_withdrawal_deletes_the_members_bundles_only(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴는 회원 행을 지우지 않아 FK CASCADE 가 돌지 않는다 — 탈퇴 파기가 묶음을 직접 지워야 이름이 남지 않는다. 다른
    회원의 묶음은 그대로다."""
    await _member(db_client, db_session)
    their_bundle = await _bundle(db_client, "남의 묶음")

    leaver_id = await _member(db_client, db_session)
    bundle_id = await _bundle(db_client, "내 묶음")
    content_id = await _draft(db_client)
    assert (await _put(db_client, bundle_id, "character", content_id)).status_code == 204

    assert (await db_client.delete("/me")).status_code == 204

    assert await db_session.scalar(sa.select(sa.func.count()).where(WorkBundle.owner_user_id == leaver_id)) == 0
    assert await _item_rows(db_session, bundle_id) == []
    assert await db_session.scalar(sa.select(WorkBundle.name).where(WorkBundle.id == their_bundle)) == "남의 묶음"
    # 작품은 비공개로 남는다(기존 탈퇴 규칙) — 묶음만 사라진다.
    assert await db_session.scalar(sa.select(Content.id).where(Content.id == content_id)) == content_id


# ── 작품 행을 건드리지 않음 ──────────────────────────────────────────────────


async def test_bundle_membership_does_not_touch_the_work_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """넣기·빼기·묶음 지우기가 작품 행(편집 시각·수정본 표시·소설화 허락)과 소설 행(수정 시각·권리 고정 칸)을 바꾸지 않는다.
    시각은 옛 값으로 박아 두어, 무엇이든 그 행을 고치면 지금 시각으로 바뀌어 드러나게 한다."""
    user_id = await _member(db_client, db_session)
    await _allow_novelize(db_session, monkeypatch, user_id)
    content_id = await _draft(db_client)
    novel_id = await _novel(db_session, user_id)
    await db_session.execute(sa.update(Content).where(Content.id == content_id).values(edited_at=_OLD, updated_at=_OLD))
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(updated_at=_OLD))
    await db_session.commit()

    async def snapshot() -> tuple[dict[str, Any], dict[str, Any]]:
        content = (await db_session.execute(sa.select(Content.__table__).where(Content.id == content_id))).one()
        novel = (await db_session.execute(sa.select(Novel.__table__).where(Novel.id == novel_id))).one()
        return dict(content._mapping), dict(novel._mapping)

    before = await snapshot()
    bundle_id = await _bundle(db_client)
    assert (await _put(db_client, bundle_id, "character", content_id)).status_code == 204
    assert (await _put(db_client, bundle_id, "novel", novel_id)).status_code == 204
    assert await snapshot() == before
    assert (await db_client.delete(f"/me/work-bundles/{bundle_id}/items/character/{content_id}")).status_code == 204
    assert (await db_client.delete(f"/me/work-bundles/{bundle_id}")).status_code == 204
    assert await snapshot() == before
