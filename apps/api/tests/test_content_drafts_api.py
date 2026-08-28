import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
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


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    """Logs in via the existing dev session-echo endpoint (same pattern as test_assets_api.py)."""
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def _get_genre(db_session: AsyncSession) -> Genre:
    result = await db_session.execute(sa.select(Genre).limit(1))
    return result.scalars().one()


async def _make_asset(db_session: AsyncSession, owner_user_id: uuid.UUID) -> Asset:
    asset = Asset(
        owner_user_id=owner_user_id, storage_key=f"assets/test/{uuid.uuid4()}", kind=AssetKind.ORIGINAL
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


async def _make_content(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    genre_id: uuid.UUID,
    content_type: ContentType = ContentType.CHARACTER,
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=content_type,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    return content


async def _add_version(
    db_session: AsyncSession,
    content: Content,
    *,
    published: bool,
    created_at: datetime | None = None,
) -> ContentVersion:
    version = ContentVersion(
        content_id=content.id,
        version_number=1 if published else None,
        published_at=datetime.now(timezone.utc) if published else None,
        detail_description="설명",
    )
    db_session.add(version)
    await db_session.flush()
    if published:
        # `_publish_character_content`/`_publish_story_content` also point the content at the
        # version they just published — the flag US-002's filter reads.
        content.current_published_version_id = version.id
        await db_session.flush()
    if created_at is not None:
        await db_session.execute(
            sa.update(ContentVersion)
            .where(ContentVersion.id == version.id)
            .values(created_at=created_at)
        )
        await db_session.refresh(version)
    return version


async def _add_character_detail(
    db_session: AsyncSession, version: ContentVersion, thumbnail: Asset, *, name: str
) -> CharacterVersionDetail:
    detail = CharacterVersionDetail(
        content_version_id=version.id,
        name=name,
        one_liner="한줄소개",
        thumbnail_asset_id=thumbnail.id,
        intro="인트로",
        example_dialogues=[],
        character_prompt="프롬프트",
    )
    db_session.add(detail)
    await db_session.flush()
    return detail


async def _add_story_detail(
    db_session: AsyncSession, version: ContentVersion, thumbnail: Asset, *, name: str
) -> StoryVersionDetail:
    detail = StoryVersionDetail(
        content_version_id=version.id,
        name=name,
        one_liner="한줄소개",
        thumbnail_asset_id=thumbnail.id,
        prompt_template=StoryPromptTemplate.BASIC,
    )
    db_session.add(detail)
    await db_session.flush()
    return detail


async def test_list_drafts_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 401


async def test_list_drafts_returns_never_published_character_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, content_type=ContentType.CHARACTER
    )
    version = await _add_version(db_session, content, published=False)
    await _add_character_detail(db_session, version, thumbnail, name="캐릭터 초안")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200

    [draft] = resp.json()["items"]
    assert draft["id"] == str(content.id)
    assert draft["type"] == "character"
    assert draft["name"] == "캐릭터 초안"
    assert draft["thumbnailAssetId"] == str(thumbnail.id)
    assert draft["thumbnailUrl"]
    assert draft["updatedAt"]


async def test_list_drafts_returns_story_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, content_type=ContentType.STORY
    )
    version = await _add_version(db_session, content, published=False)
    await _add_story_detail(db_session, version, thumbnail, name="스토리 초안")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200

    [draft] = resp.json()["items"]
    assert draft["type"] == "story"
    assert draft["name"] == "스토리 초안"


async def test_list_drafts_excludes_content_with_no_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    version = await _add_version(db_session, content, published=True)
    await _add_character_detail(db_session, version, thumbnail, name="발행됨")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_list_drafts_excludes_published_content_with_auto_cloned_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """US-002. 발행하면 다음 편집용 초안이 자동 복제되므로 발행작에도 미발행 버전이 항상 딸려
    있다 — 그래도 초안 목록에는 나오지 않아야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    published_version = await _add_version(db_session, content, published=True)
    await _add_character_detail(db_session, published_version, thumbnail, name="발행 버전")
    draft_version = await _add_version(db_session, content, published=False)
    await _add_character_detail(db_session, draft_version, thumbnail, name="재발행용 초안")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_list_drafts_drops_content_once_it_is_published(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """US-002. 같은 콘텐츠를 발행 전/후 두 상태에서 본다 — 발행 전에는 초안으로 잡히고,
    발행하는 순간 목록에서 빠진다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    first_version = await _add_version(db_session, content, published=False)
    await _add_character_detail(db_session, first_version, thumbnail, name="작성 중")
    await db_session.commit()

    await _login_as(db_client, user.id)
    before = await db_client.get("/me/drafts")
    assert before.status_code == 200
    assert [draft["name"] for draft in before.json()["items"]] == ["작성 중"]

    # 발행: 이 버전이 발행본이 되고, 다음 편집용 초안이 자동 복제된다.
    first_version.version_number = 1
    first_version.published_at = datetime.now(timezone.utc)
    content.current_published_version_id = first_version.id
    cloned_draft = await _add_version(db_session, content, published=False)
    await _add_character_detail(db_session, cloned_draft, thumbnail, name="작성 중")
    await db_session.commit()

    after = await db_client.get("/me/drafts")
    assert after.status_code == 200
    assert after.json()["items"] == []


async def test_list_drafts_only_returns_own_drafts(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, other.id)

    content = await _make_content(db_session, creator_user_id=other.id, genre_id=genre.id)
    version = await _add_version(db_session, content, published=False)
    await _add_character_detail(db_session, version, thumbnail, name="다른 사람 초안")
    await db_session.commit()

    await _login_as(db_client, owner.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_list_drafts_uses_latest_draft_row_when_multiple_exist(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    now = datetime.now(timezone.utc)
    older_version = await _add_version(
        db_session, content, published=False, created_at=now - timedelta(hours=1)
    )
    await _add_character_detail(db_session, older_version, thumbnail, name="오래된 초안")
    newer_version = await _add_version(db_session, content, published=False, created_at=now)
    await _add_character_detail(db_session, newer_version, thumbnail, name="최신 초안")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200

    [draft] = resp.json()["items"]
    assert draft["name"] == "최신 초안"


async def test_list_drafts_paginates_at_page_size_without_duplicates(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """US-001. `/me/drafts`도 `/users/{id}/contents`와 같은 페이지 크기(24)·같은 봉투를 쓴다.

    `Content.updated_at`은 server default라 이 테스트의 25건이 **전부 같은 시각**을 갖는다(하나의
    바깥 트랜잭션 안에서 `now()`가 고정되기 때문 — apps/api/CLAUDE.md). 그래서 순서는 tiebreaker인
    `id DESC`가 정하고, 그 사실이 곧 "동시각 25건에서도 페이지가 겹치거나 새지 않는다"의 검증이 된다.
    """
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    total = 25
    for index in range(total):
        content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
        version = await _add_version(db_session, content, published=False)
        await _add_character_detail(db_session, version, thumbnail, name=f"초안-{index:02d}")
    await db_session.commit()

    await _login_as(db_client, user.id)

    pages: list[list[dict[str, object]]] = []
    cursors: list[str | None] = []
    cursor: str | None = None
    for _ in range(10):
        params = {"cursor": cursor} if cursor is not None else {}
        resp = await db_client.get("/me/drafts", params=params)
        assert resp.status_code == 200
        body = resp.json()
        pages.append(body["items"])
        cursor = body["nextCursor"]
        cursors.append(cursor)
        if cursor is None:
            break
    else:
        raise AssertionError("커서가 10페이지 안에 끝나지 않았다")

    assert [len(page) for page in pages] == [24, 1]
    assert cursors[0] is not None
    assert cursors[-1] is None

    collected = [draft["id"] for page in pages for draft in page]
    assert len(collected) == total
    assert len(set(collected)) == total

    all_ids = set(
        (
            await db_session.scalars(
                sa.select(Content.id).where(
                    Content.creator_user_id == user.id,
                    Content.current_published_version_id.is_(None),
                )
            )
        ).all()
    )
    assert {uuid.UUID(str(content_id)) for content_id in collected} == all_ids


async def test_list_drafts_cursor_excludes_published_content_across_pages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """US-001. 커서에는 정렬 키만 들어 있으므로 "발행작 제외" 조건이 페이지마다 다시 걸려야 한다.
    발행작을 초안들 사이에 끼워 두고 페이지 경계를 넘겨도 새지 않는지 본다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    draft_total = 25
    for index in range(draft_total):
        content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
        version = await _add_version(db_session, content, published=False)
        await _add_character_detail(db_session, version, thumbnail, name=f"초안-{index:02d}")
    for index in range(3):
        published = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
        published_version = await _add_version(db_session, published, published=True)
        await _add_character_detail(db_session, published_version, thumbnail, name=f"발행-{index}")
        cloned_draft = await _add_version(db_session, published, published=False)
        await _add_character_detail(db_session, cloned_draft, thumbnail, name=f"발행-{index}")
    await db_session.commit()

    await _login_as(db_client, user.id)

    names: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params = {"cursor": cursor} if cursor is not None else {}
        resp = await db_client.get("/me/drafts", params=params)
        assert resp.status_code == 200
        body = resp.json()
        names.extend(draft["name"] for draft in body["items"])
        cursor = body["nextCursor"]
        if cursor is None:
            break
    else:
        raise AssertionError("커서가 10페이지 안에 끝나지 않았다")

    assert sorted(names) == sorted(f"초안-{index:02d}" for index in range(draft_total))
