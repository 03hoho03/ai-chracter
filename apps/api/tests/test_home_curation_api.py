"""홈 큐레이션 공개 읽기(`GET /home-curation`). 지정 행은 테스트가 직접 넣는다 — 어드민 쓰기 경로는
`test_admin_home_curation_api.py` 가 따로 본다."""

from collections.abc import Callable

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.redis import redis_client
from api.db.models import (
    Content,
    ContentType,
    ContentVisibility,
    HomeCuration,
    ModerationStatus,
    StoryVersionDetail,
)
from factories import _get_genre, _login_as, _make_published_character, _make_published_story, _make_user


async def _curated_story(db_session: AsyncSession) -> Content:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=creator.id, genre_id=genre.id)
    db_session.add(HomeCuration(content_type=ContentType.STORY, content_id=content.id))
    await db_session.commit()
    return content


async def test_returns_null_item_when_nothing_is_curated(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/home-curation", params={"type": "story"})

    assert resp.status_code == 200
    assert resp.json() == {"item": None}


async def test_returns_the_curated_work_with_its_one_liner_and_thumbnail(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content = await _curated_story(db_session)

    resp = await db_client.get("/home-curation", params={"type": "story"})

    assert resp.status_code == 200
    item = resp.json()["item"]
    assert {key: item[key] for key in ("id", "type", "name", "oneLiner")} == {
        "id": str(content.id),
        "type": "story",
        "name": "스토리",
        "oneLiner": "한줄소개",
    }
    # 그리드 카드와 같은 512px 축소본을 서명한다 — 원본은 첫 화면에 싣기엔 무겁다.
    assert "_thumb.webp" in item["thumbnailUrl"]


async def test_curated_work_carries_its_default_user_name(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """응답은 보는 사람과 무관하다 — 프로필 없는 사람·비로그인 홈이 한줄소개의 `{{user}}` 를 바꿀 이름을 함께 싣는다."""
    content = await _curated_story(db_session)
    assert content.current_published_version_id is not None
    detail = await db_session.get(StoryVersionDetail, content.current_published_version_id)
    assert detail is not None
    detail.default_user_name = "모험가"
    await db_session.commit()

    resp = await db_client.get("/home-curation", params={"type": "story"})

    assert resp.json()["item"]["defaultUserName"] == "모험가"


async def test_each_type_reads_its_own_slot(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    story = await _curated_story(db_session)
    genre = await _get_genre(db_session)
    character = await _make_published_character(
        db_session, creator_user_id=story.creator_user_id, genre_id=genre.id
    )
    db_session.add(HomeCuration(content_type=ContentType.CHARACTER, content_id=character.id))
    await db_session.commit()

    story_item = (await db_client.get("/home-curation", params={"type": "story"})).json()["item"]
    character_item = (await db_client.get("/home-curation", params={"type": "character"})).json()["item"]

    assert (story_item["id"], story_item["type"]) == (str(story.id), "story")
    assert (character_item["id"], character_item["type"]) == (str(character.id), "character")


def _make_private(content: Content) -> None:
    content.visibility = ContentVisibility.PRIVATE


def _make_link_only(content: Content) -> None:
    content.visibility = ContentVisibility.LINK


def _restrict(content: Content) -> None:
    content.moderation_status = ModerationStatus.RESTRICTED


def _delete(content: Content) -> None:
    content.moderation_status = ModerationStatus.DELETED


def _unpublish(content: Content) -> None:
    content.current_published_version_id = None


@pytest.mark.parametrize(
    "hide",
    [
        pytest.param(_make_private, id="private"),
        pytest.param(_make_link_only, id="link-only"),
        pytest.param(_restrict, id="restricted"),
        pytest.param(_delete, id="deleted"),
        pytest.param(_unpublish, id="unpublished"),
    ],
)
async def test_hides_a_curated_work_that_the_public_list_would_not_show(
    db_client: httpx.AsyncClient, db_session: AsyncSession, hide: Callable[[Content], None]
) -> None:
    content = await _curated_story(db_session)
    hide(content)
    await db_session.commit()

    resp = await db_client.get("/home-curation", params={"type": "story"})

    assert resp.json() == {"item": None}


async def test_hides_a_curated_work_without_a_genre(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """장르는 조건이 아니라 홈 목록의 내부 조인이 거른다 — 발행작도 초안 저장으로 장르가 비면 목록에서 빠진다."""
    content = await _curated_story(db_session)
    content.genre_id = None
    await db_session.commit()

    resp = await db_client.get("/home-curation", params={"type": "story"})

    assert resp.json() == {"item": None}


async def test_lifting_a_restriction_shows_the_curated_work_again(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """제한해도 지정은 지우지 않으므로 해제하면 운영자가 다시 지정하지 않아도 돌아온다."""
    content = await _curated_story(db_session)
    content.moderation_status = ModerationStatus.RESTRICTED
    await db_session.commit()
    assert (await db_client.get("/home-curation", params={"type": "story"})).json() == {"item": None}

    content.moderation_status = ModerationStatus.NORMAL
    await db_session.commit()

    item = (await db_client.get("/home-curation", params={"type": "story"})).json()["item"]
    assert item["id"] == str(content.id)


async def test_reading_the_curation_does_not_count_a_view(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """홈은 방문마다 이 API 를 부른다. 상세 GET 처럼 조회수를 올리면 홈을 연 사람 수가 그 작품의 조회수가 된다."""
    content = await _curated_story(db_session)
    viewer = _make_user()
    db_session.add(viewer)
    await db_session.commit()

    assert (await db_client.get("/home-curation", params={"type": "story"})).status_code == 200
    await _login_as(db_client, viewer.id)
    assert (await db_client.get("/home-curation", params={"type": "story"})).status_code == 200

    view_count = await db_session.scalar(sa.select(Content.view_count).where(Content.id == content.id))
    assert view_count == 0
    assert await redis_client.keys(f"view:{content.id}:*") == []
