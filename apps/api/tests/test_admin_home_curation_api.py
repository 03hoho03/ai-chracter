"""어드민 홈 큐레이션 지정·해제·현황(`/admin/home-curations`)."""

import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    AdminActionLog,
    Content,
    ContentType,
    ContentVisibility,
    HomeCuration,
    ModerationStatus,
)
from factories import (
    _create_admin,
    _get_genre,
    _login_as,
    _login_as_admin,
    _make_published_character,
    _make_published_story,
    _make_user,
)


async def _story(db_session: AsyncSession) -> Content:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()
    return content


async def _character(db_session: AsyncSession) -> Content:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()
    return content


async def _as_admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)


async def _curations(db_session: AsyncSession) -> dict[ContentType, uuid.UUID]:
    rows = (await db_session.execute(sa.select(HomeCuration.content_type, HomeCuration.content_id))).all()
    return {content_type: content_id for content_type, content_id in rows}


async def _curation_logs(db_session: AsyncSession) -> list[tuple[str, uuid.UUID | None, str]]:
    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog)
            .where(AdminActionLog.action_type.in_(["home-curation-set", "home-curation-clear"]))
            .order_by(AdminActionLog.created_at)
        )
    ).all()
    return [(log.action_type, log.target_content_id, log.reason_text) for log in logs]


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        pytest.param("get", "/admin/home-curations", None, id="list"),
        pytest.param("put", "/admin/home-curations/story", {"contentId": str(uuid.uuid4())}, id="set"),
        pytest.param("delete", "/admin/home-curations/story", None, id="clear"),
    ],
)
async def test_requires_admin_session(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    method: str,
    path: str,
    json: dict[str, object] | None,
) -> None:
    assert (await db_client.request(method.upper(), path, json=json)).status_code == 401

    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    # 일반 세션이 실제로 서 있음을 먼저 고정해야 "일반 사용자로는 401" 이 무세션 401 과 갈린다.
    assert (await db_client.get("/me")).status_code == 200

    assert (await db_client.request(method.upper(), path, json=json)).status_code == 401


async def test_set_curates_the_work_and_logs_it_with_the_comment(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content = await _story(db_session)
    await _as_admin(db_client, db_session)

    resp = await db_client.put(
        "/admin/home-curations/story", json={"contentId": str(content.id), "adminComment": "가을 추천"}
    )

    assert resp.status_code == 204
    assert await _curations(db_session) == {ContentType.STORY: content.id}
    assert await _curation_logs(db_session) == [("home-curation-set", content.id, "가을 추천")]


async def test_set_without_a_comment_is_allowed(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """되돌릴 수 있고 작가에게 불이익이 없는 조작이라 코멘트를 강제하지 않는다."""
    content = await _story(db_session)
    await _as_admin(db_client, db_session)

    resp = await db_client.put("/admin/home-curations/story", json={"contentId": str(content.id)})

    assert resp.status_code == 204
    assert await _curation_logs(db_session) == [("home-curation-set", content.id, "")]


async def test_set_replaces_the_previous_work_of_the_same_type_only(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    first = await _story(db_session)
    second = await _story(db_session)
    character = await _character(db_session)
    await _as_admin(db_client, db_session)

    for content_type, content in (("story", first), ("character", character), ("story", second)):
        resp = await db_client.put(f"/admin/home-curations/{content_type}", json={"contentId": str(content.id)})
        assert resp.status_code == 204

    assert await _curations(db_session) == {ContentType.STORY: second.id, ContentType.CHARACTER: character.id}


async def test_set_rejects_a_work_of_the_other_type(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    character = await _character(db_session)
    await _as_admin(db_client, db_session)

    resp = await db_client.put("/admin/home-curations/story", json={"contentId": str(character.id)})

    assert resp.status_code == 400
    assert resp.json()["detail"] == {"code": "CONTENT_TYPE_MISMATCH"}
    assert await _curations(db_session) == {}
    assert await _curation_logs(db_session) == []


async def test_set_rejects_a_work_the_public_list_does_not_show(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """지정했는데 홈에 안 보이는 혼란을 지정 시점에 막는다. 판정은 공개 목록과 같은 조건이다."""
    content = await _story(db_session)
    content.visibility = ContentVisibility.PRIVATE
    await db_session.commit()
    await _as_admin(db_client, db_session)

    resp = await db_client.put("/admin/home-curations/story", json={"contentId": str(content.id)})

    assert resp.status_code == 400
    assert resp.json()["detail"] == {"code": "NOT_PUBLICLY_LISTED"}
    assert await _curations(db_session) == {}


async def test_set_rejects_a_work_without_a_genre(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """공개 조건은 통과해도 홈 목록의 장르 조인에서 빠지는 작품이다 — 어드민이 홈과 다르게 판정하면 안 된다."""
    content = await _story(db_session)
    content.genre_id = None
    await db_session.commit()
    await _as_admin(db_client, db_session)

    resp = await db_client.put("/admin/home-curations/story", json={"contentId": str(content.id)})

    assert resp.status_code == 400
    assert resp.json()["detail"] == {"code": "NOT_PUBLICLY_LISTED"}


async def test_curation_logs_stay_out_of_the_authors_action_history(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작가 상세의 조치 이력은 최근 20행뿐이라 지정을 몇 번 바꾸면 제재 기록이 밀려난다. 감사 로그 행은 남는다."""
    content = await _story(db_session)
    await _as_admin(db_client, db_session)
    restrict_resp = await db_client.post(
        f"/admin/contents/{content.id}/action", json={"action": "restrict", "reasonCategory": "spam"}
    )
    assert restrict_resp.status_code == 200
    # 제재 기록을 하나 남긴 뒤 다시 지정할 수 있게 상태만 되돌린다(해제 조치를 쓰면 로그가 하나 더 생긴다).
    await db_session.refresh(content)
    content.moderation_status = ModerationStatus.NORMAL
    await db_session.commit()
    for _ in range(2):
        resp = await db_client.put("/admin/home-curations/story", json={"contentId": str(content.id)})
        assert resp.status_code == 204
    assert (await db_client.delete("/admin/home-curations/story")).status_code == 204

    detail = (await db_client.get(f"/admin/users/{content.creator_user_id}")).json()

    assert [log["actionType"] for log in detail["actionLogs"]] == ["content-restrict"]
    # 한 트랜잭션 안이라 `created_at` 이 같다 — 순서 대신 개수로 본다.
    assert sorted(action for action, _, _ in await _curation_logs(db_session)) == [
        "home-curation-clear",
        "home-curation-set",
        "home-curation-set",
    ]


async def test_set_returns_404_for_an_unknown_work(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _as_admin(db_client, db_session)

    resp = await db_client.put("/admin/home-curations/story", json={"contentId": str(uuid.uuid4())})

    # 문구까지 본다 — 라우트가 없어도 404 라 상태 코드만으로는 "작품이 없다" 를 판정하지 못한다.
    assert (resp.status_code, resp.json()["detail"]) == (404, "Content not found")


async def test_clear_removes_the_curation_and_logs_the_work_it_removed(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    story = await _story(db_session)
    character = await _character(db_session)
    db_session.add_all(
        [
            HomeCuration(content_type=ContentType.STORY, content_id=story.id),
            HomeCuration(content_type=ContentType.CHARACTER, content_id=character.id),
        ]
    )
    await db_session.commit()
    await _as_admin(db_client, db_session)

    resp = await db_client.request("DELETE", "/admin/home-curations/story", json={"adminComment": "교체 예정"})

    assert resp.status_code == 204
    assert await _curations(db_session) == {ContentType.CHARACTER: character.id}
    assert await _curation_logs(db_session) == [("home-curation-clear", story.id, "교체 예정")]


async def test_clear_without_a_curation_is_a_no_op(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """누를 때마다 같은 결과라 다시 눌러도 막지 않는다. 지운 작품이 없으니 감사 로그에 남길 대상도 없다."""
    await _as_admin(db_client, db_session)

    resp = await db_client.delete("/admin/home-curations/story")

    assert resp.status_code == 204
    assert await _curation_logs(db_session) == []


async def test_list_shows_each_type_and_whether_the_home_shows_it_now(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """지정 뒤 작품이 이용제한되면 지정은 남고 홈에서만 빠진다 — 운영자가 그 차이를 목록에서 본다."""
    story = await _story(db_session)
    character = await _character(db_session)
    db_session.add_all(
        [
            HomeCuration(content_type=ContentType.STORY, content_id=story.id),
            HomeCuration(content_type=ContentType.CHARACTER, content_id=character.id),
        ]
    )
    character.moderation_status = ModerationStatus.RESTRICTED
    await db_session.commit()
    await _as_admin(db_client, db_session)

    resp = await db_client.get("/admin/home-curations")

    assert resp.status_code == 200
    by_type = {item["type"]: item for item in resp.json()["items"]}
    assert by_type["story"]["content"]["id"] == str(story.id)
    assert by_type["story"]["content"]["name"] == "스토리"
    assert by_type["story"]["isListed"] is True
    assert by_type["character"]["content"]["id"] == str(character.id)
    assert by_type["character"]["content"]["moderationStatus"] == "restricted"
    assert by_type["character"]["isListed"] is False


async def test_list_shows_empty_slots_for_uncurated_types(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _as_admin(db_client, db_session)

    resp = await db_client.get("/admin/home-curations")

    assert resp.json() == {
        "items": [
            {"type": "story", "content": None, "isListed": False},
            {"type": "character", "content": None, "isListed": False},
        ]
    }
