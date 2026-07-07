import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Asset,
    AssetKind,
    CharacterVersionDetail,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
)


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(timezone.utc),
        "privacy_agreed_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return User(**defaults)


async def _get_genres(db_session: AsyncSession) -> list[Genre]:
    result = await db_session.execute(sa.select(Genre).order_by(Genre.sort_order))
    return list(result.scalars().all())


async def _make_asset(db_session: AsyncSession, owner_user_id: uuid.UUID) -> Asset:
    asset = Asset(
        owner_user_id=owner_user_id, storage_key=f"assets/test/{uuid.uuid4()}", kind=AssetKind.ORIGINAL
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


async def _make_published_content(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    genre_id: uuid.UUID,
    content_type: ContentType = ContentType.CHARACTER,
    visibility: ContentVisibility = ContentVisibility.PUBLIC,
    moderation_status: ModerationStatus = ModerationStatus.NORMAL,
    name: str,
    one_liner: str = "한줄소개",
    detail_description: str = "설명",
    hashtags: list[str] | None = None,
    view_count: int = 0,
    like_count: int = 0,
    chat_count: int = 0,
    created_at: datetime | None = None,
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=content_type,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=hashtags or [],
        visibility=visibility,
        moderation_status=moderation_status,
        view_count=view_count,
        like_count=like_count,
        chat_count=chat_count,
    )
    db_session.add(content)
    await db_session.flush()
    if created_at is not None:
        content.created_at = created_at
        await db_session.flush()

    version = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(timezone.utc),
        detail_description=detail_description,
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = await _make_asset(db_session, creator_user_id)
    if content_type == ContentType.CHARACTER:
        db_session.add(
            CharacterVersionDetail(
                content_version_id=version.id,
                name=name,
                one_liner=one_liner,
                thumbnail_asset_id=thumbnail.id,
                intro="인트로",
                example_dialogues=[],
                character_prompt="프롬프트",
            )
        )
    else:
        db_session.add(
            StoryVersionDetail(
                content_version_id=version.id,
                name=name,
                one_liner=one_liner,
                thumbnail_asset_id=thumbnail.id,
                prompt_template=StoryPromptTemplate.BASIC,
            )
        )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def test_list_genres_returns_seed_data_in_sort_order(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/genres")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 10
    assert [g["sortOrder"] for g in body] == sorted(g["sortOrder"] for g in body)
    assert body[0]["name"] == "로맨스"


async def test_list_contents_only_returns_public_normal_published(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = (await _get_genres(db_session))[0]

    await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, name="공개-정상"
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        visibility=ContentVisibility.LINK,
        name="링크공개",
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        visibility=ContentVisibility.PRIVATE,
        name="비공개",
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        moderation_status=ModerationStatus.RESTRICTED,
        name="이용제한",
    )
    await db_session.commit()

    resp = await db_client.get("/contents", params={"type": "character"})
    assert resp.status_code == 200
    body = resp.json()
    assert [item["name"] for item in body["items"]] == ["공개-정상"]
    assert body["nextCursor"] is None


async def test_list_contents_excludes_never_published_drafts(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = (await _get_genres(db_session))[0]

    content = Content(
        creator_user_id=user.id,
        type=ContentType.CHARACTER,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    draft_version = ContentVersion(
        content_id=content.id, version_number=None, published_at=None, detail_description="설명"
    )
    db_session.add(draft_version)
    await db_session.flush()
    thumbnail = await _make_asset(db_session, user.id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=draft_version.id,
            name="초안",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    await db_session.commit()

    resp = await db_client.get("/contents", params={"type": "character"})
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_list_contents_filters_by_type(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = (await _get_genres(db_session))[0]

    await _make_published_content(db_session, creator_user_id=user.id, genre_id=genre.id, name="캐릭터")
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        content_type=ContentType.STORY,
        name="스토리",
    )
    await db_session.commit()

    resp = await db_client.get("/contents", params={"type": "story"})
    assert resp.status_code == 200
    [item] = resp.json()["items"]
    assert item["name"] == "스토리"
    assert item["type"] == "story"


async def test_list_contents_response_includes_card_fields(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(nickname="작가님")
    db_session.add(user)
    await db_session.flush()
    genre = (await _get_genres(db_session))[0]

    content = await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, name="공개 캐릭터", view_count=7
    )
    await db_session.commit()

    resp = await db_client.get("/contents", params={"type": "character"})
    assert resp.status_code == 200
    [item] = resp.json()["items"]
    assert item["id"] == str(content.id)
    assert item["name"] == "공개 캐릭터"
    assert item["viewCount"] == 7
    assert item["creatorUserId"] == str(user.id)
    assert item["creatorNickname"] == "작가님"
    assert item["thumbnailUrl"] is not None


async def test_list_contents_search_matches_name_one_liner_and_description(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = (await _get_genres(db_session))[0]

    await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, name="마법사 이야기"
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        name="아무개",
        one_liner="마법 학교 판타지",
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        name="다른이름",
        detail_description="여긴 마법 대륙입니다",
    )
    await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, name="무관한 항목"
    )
    await db_session.commit()

    resp = await db_client.get("/contents", params={"type": "character", "q": "마법"})
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()["items"]}
    assert names == {"마법사 이야기", "아무개", "다른이름"}


async def test_list_contents_filters_by_genre_creator_and_hashtag(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_a = _make_user()
    user_b = _make_user()
    db_session.add_all([user_a, user_b])
    await db_session.flush()
    genres = await _get_genres(db_session)

    target = await _make_published_content(
        db_session,
        creator_user_id=user_a.id,
        genre_id=genres[0].id,
        name="타겟",
        hashtags=["힐링", "일상"],
    )
    await _make_published_content(
        db_session,
        creator_user_id=user_a.id,
        genre_id=genres[1].id,
        name="다른장르",
        hashtags=["힐링"],
    )
    await _make_published_content(
        db_session,
        creator_user_id=user_b.id,
        genre_id=genres[0].id,
        name="다른작가",
        hashtags=["힐링"],
    )
    await _make_published_content(
        db_session,
        creator_user_id=user_a.id,
        genre_id=genres[0].id,
        name="다른해시태그",
        hashtags=["SF"],
    )
    await db_session.commit()

    resp = await db_client.get(
        "/contents",
        params={
            "type": "character",
            "genre": str(genres[0].id),
            "creator": str(user_a.id),
            "hashtag": "힐링",
        },
    )
    assert resp.status_code == 200
    [item] = resp.json()["items"]
    assert item["id"] == str(target.id)


async def test_list_contents_sort_popular_prioritizes_chat_count_over_like_and_view(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = (await _get_genres(db_session))[0]

    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        name="대화수낮음-좋아요조회수높음",
        chat_count=1,
        like_count=100,
        view_count=100,
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        name="대화수높음-좋아요조회수낮음",
        chat_count=2,
        like_count=0,
        view_count=0,
    )
    await db_session.commit()

    resp = await db_client.get("/contents", params={"type": "character", "sort": "popular"})
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()["items"]]
    assert names == ["대화수높음-좋아요조회수낮음", "대화수낮음-좋아요조회수높음"]


async def test_list_contents_sort_genre_orders_by_genre_master_sort_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genres = await _get_genres(db_session)
    now = datetime.now(timezone.utc)

    # Older content in the earlier-sort_order genre should still rank first.
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genres[1].id,
        name="장르2-오래됨",
        created_at=now - timedelta(days=1),
    )
    await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genres[0].id,
        name="장르1-최근",
        created_at=now,
    )
    await db_session.commit()

    resp = await db_client.get("/contents", params={"type": "character", "sort": "genre"})
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()["items"]]
    assert names == ["장르1-최근", "장르2-오래됨"]


async def test_list_contents_cursor_pagination_covers_all_items_without_duplicates(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("api.content.router.CONTENT_LIST_PAGE_SIZE", 2)

    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = (await _get_genres(db_session))[0]
    now = datetime.now(timezone.utc)

    expected_names = [f"항목-{i}" for i in range(5)]
    for i, name in enumerate(expected_names):
        await _make_published_content(
            db_session,
            creator_user_id=user.id,
            genre_id=genre.id,
            name=name,
            created_at=now - timedelta(minutes=i),
        )
    await db_session.commit()

    collected: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, str] = {"type": "character"}
        if cursor is not None:
            params["cursor"] = cursor
        resp = await db_client.get("/contents", params=params)
        assert resp.status_code == 200
        body = resp.json()
        collected.extend(item["name"] for item in body["items"])
        cursor = body["nextCursor"]
        if cursor is None:
            break

    assert collected == expected_names
