import base64
import json
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.content.router import CONTENT_LIST_PAGE_SIZE
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


async def test_list_signs_thumbnail_variant_while_detail_signs_original(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """US-008: list responses sign the `_thumb.webp` variant key; the detail view
    keeps signing the original object (original extension)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = (await _get_genres(db_session))[0]

    content = await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, name="캐릭터"
    )
    detail = await db_session.scalar(
        sa.select(CharacterVersionDetail).where(
            CharacterVersionDetail.content_version_id == content.current_published_version_id
        )
    )
    assert detail is not None and detail.thumbnail_asset_id is not None
    asset = await db_session.get(Asset, detail.thumbnail_asset_id)
    assert asset is not None
    asset.storage_key = f"{asset.storage_key}.png"
    await db_session.commit()

    list_resp = await db_client.get("/contents", params={"type": "character"})
    assert list_resp.status_code == 200
    [item] = list_resp.json()["items"]
    assert "_thumb.webp" in item["thumbnailUrl"]

    detail_resp = await db_client.get(f"/contents/{content.id}")
    assert detail_resp.status_code == 200
    detail_url = detail_resp.json()["thumbnailUrl"]
    assert "_thumb.webp" not in detail_url
    assert ".png" in detail_url


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


async def test_list_contents_sort_popular_orders_by_view_count_when_chat_and_like_tie(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = (await _get_genres(db_session))[0]

    for name, view_count in [("조회42", 42), ("조회0", 0), ("조회250", 250), ("조회3", 3)]:
        await _make_published_content(
            db_session,
            creator_user_id=user.id,
            genre_id=genre.id,
            name=name,
            chat_count=5,
            like_count=7,
            view_count=view_count,
        )
    await db_session.commit()

    resp = await db_client.get("/contents", params={"type": "character", "sort": "popular"})
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()["items"]]
    assert names == ["조회250", "조회42", "조회3", "조회0"]


async def test_list_contents_sort_popular_cursor_covers_all_items_with_nonzero_view_counts(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = (await _get_genres(db_session))[0]

    contents_by_view: dict[int, uuid.UUID] = {}
    for i in range(CONTENT_LIST_PAGE_SIZE * 2 + 5):
        view_count = i * 3 + 1
        content = await _make_published_content(
            db_session,
            creator_user_id=user.id,
            genre_id=genre.id,
            name=f"인기-{i}",
            chat_count=5,
            like_count=7,
            view_count=view_count,
        )
        contents_by_view[view_count] = content.id
    await db_session.commit()

    views_desc = sorted(contents_by_view, reverse=True)
    expected_ids = [str(contents_by_view[v]) for v in views_desc]

    collected: list[str] = []
    cursors: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, str] = {"type": "character", "sort": "popular"}
        if cursor is not None:
            params["cursor"] = cursor
        resp = await db_client.get("/contents", params=params)
        assert resp.status_code == 200
        body = resp.json()
        collected.extend(item["id"] for item in body["items"])
        cursor = body["nextCursor"]
        if cursor is None:
            break
        cursors.append(cursor)

    assert len(cursors) >= 2
    assert collected == expected_ids

    # 커서가 0이 아닌 view_count를 문자열로 담았다가 int()로 되돌리는 왕복 확인
    first_cursor_parts = json.loads(base64.urlsafe_b64decode(cursors[0].encode()).decode())
    boundary_view_count = views_desc[CONTENT_LIST_PAGE_SIZE - 1]
    assert first_cursor_parts[2] == str(boundary_view_count)
    assert int(first_cursor_parts[2]) == boundary_view_count > 0


async def test_list_contents_sort_popular_next_page_survives_view_count_change(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = (await _get_genres(db_session))[0]

    contents: list[Content] = []
    for i in range(CONTENT_LIST_PAGE_SIZE + 5):
        contents.append(
            await _make_published_content(
                db_session,
                creator_user_id=user.id,
                genre_id=genre.id,
                name=f"변동-{i}",
                chat_count=5,
                like_count=7,
                view_count=i + 1,
            )
        )
    await db_session.commit()

    resp = await db_client.get("/contents", params={"type": "character", "sort": "popular"})
    assert resp.status_code == 200
    body = resp.json()
    first_page_ids = {item["id"] for item in body["items"]}
    cursor = body["nextCursor"]
    assert cursor is not None

    # 첫 페이지에 없는 작품을 경계 너머로 밀어 올려도 다음 페이지 요청이 깨지지 않아야 한다
    # (값 기반 커서라 항목이 밀리거나 겹칠 수는 있다 — 여기서는 200과 정상 종료만 고정)
    off_page = next(c for c in contents if str(c.id) not in first_page_ids)
    off_page.view_count = 10_000
    await db_session.commit()

    for _ in range(10):
        resp = await db_client.get(
            "/contents", params={"type": "character", "sort": "popular", "cursor": cursor}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["items"], list)
        cursor = body["nextCursor"]
        if cursor is None:
            break
    assert cursor is None


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
