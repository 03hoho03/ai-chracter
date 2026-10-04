import uuid
from datetime import datetime, timedelta, timezone, UTC
from urllib.parse import urlparse

import httpx
import pytest
import sqlalchemy as sa
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.redis import redis_client
from api.core.s3 import build_display_key

from api.db.models import (
    Asset,
    AssetKind,
    CharacterVersionDetail,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Favorite,
    Like,
    ModerationStatus,
    StartingSetup,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
)
from factories import _get_genre, _login_as, _make_asset, _make_user, _set_signing_clock


async def _make_published_content(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    genre_id: uuid.UUID,
    content_type: ContentType = ContentType.CHARACTER,
    visibility: ContentVisibility = ContentVisibility.PUBLIC,
    moderation_status: ModerationStatus = ModerationStatus.NORMAL,
    name: str = "이름",
    one_liner: str = "한줄소개",
    detail_description: str = "상세설명",
    hashtags: list[str] | None = None,
    chat_count: int = 0,
    like_count: int = 0,
    version_number: int = 1,
) -> tuple[Content, ContentVersion]:
    content = Content(
        creator_user_id=creator_user_id,
        type=content_type,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=hashtags or [],
        visibility=visibility,
        moderation_status=moderation_status,
        chat_count=chat_count,
        like_count=like_count,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id,
        version_number=version_number,
        published_at=datetime.now(UTC),
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
    return content, version


async def _add_starting_setup(
    db_session: AsyncSession, *, content_version_id: uuid.UUID, name: str, prologue: str, order: int
) -> StartingSetup:
    setup = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=content_version_id,
        name=name,
        prologue=prologue,
        order=order,
    )
    db_session.add(setup)
    await db_session.flush()
    return setup


async def test_get_content_detail_returns_meta_metrics_and_version_fields(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(nickname="작가님")
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, _version = await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        name="공개 캐릭터",
        one_liner="한줄",
        detail_description="상세",
        hashtags=["힐링"],
        chat_count=3,
        like_count=5,
    )
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(content.id)
    assert body["type"] == "character"
    assert body["name"] == "공개 캐릭터"
    assert body["thumbnailUrl"] is not None
    assert body["creatorUserId"] == str(user.id)
    assert body["creatorNickname"] == "작가님"
    assert body["genreId"] == str(genre.id)
    assert body["genreName"] == genre.name
    assert body["hashtags"] == ["힐링"]
    assert body["oneLiner"] == "한줄"
    assert body["detailDescription"] == "상세"
    assert body["chatCount"] == 3
    assert body["likeCount"] == 5
    assert body["isLiked"] is False
    assert body["isFavorited"] is False
    assert body["startingSetups"] is None
    assert body["versionNumber"] == 1
    assert body["isOwner"] is False
    assert body["accessStatus"] == {"kind": "accessible", "visibility": "public"}


def _url_key(url: str) -> str:
    """서명 URL 이 가리키는 객체 키(경로에서 버킷 이름을 뗀 나머지)."""
    return urlparse(url).path.split("/", 2)[2]


async def _thumbnail_asset(db_session: AsyncSession, version: ContentVersion, content_type: ContentType) -> Asset:
    thumbnail_asset_id = (
        await db_session.scalar(
            sa.select(CharacterVersionDetail.thumbnail_asset_id).where(
                CharacterVersionDetail.content_version_id == version.id
            )
        )
        if content_type == ContentType.CHARACTER
        else await db_session.scalar(
            sa.select(StoryVersionDetail.thumbnail_asset_id).where(StoryVersionDetail.content_version_id == version.id)
        )
    )
    assert thumbnail_asset_id is not None
    asset = await db_session.get(Asset, thumbnail_asset_id)
    assert asset is not None
    return asset


@pytest.mark.parametrize("content_type", [ContentType.CHARACTER, ContentType.STORY])
@pytest.mark.parametrize(
    ("kind", "storage_key"),
    [
        # 작가가 올린 대표 이미지, 빌더가 복사 없이 거는 생성 이미지, 블러본 — 대표 이미지가 될 수 있는 자산
        # 종류마다 원래 확장자가 달라도 같은 규칙으로 표시용 변형 키가 나와야 한다.
        (AssetKind.ORIGINAL, "assets/content-thumbnail/{id}.webp"),
        (AssetKind.GENERATED, "assets/generated/{id}.png"),
        (AssetKind.BLURRED, "assets/situational-image-blurred/{id}.png"),
    ],
)
async def test_get_content_detail_signs_the_display_variant_of_the_thumbnail(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    content_type: ContentType,
    kind: AssetKind,
    storage_key: str,
) -> None:
    """상세 히어로·채팅방 헤더 아바타·링크 미리보기가 이 주소를 그대로 쓴다. 원본은 장당 1MB 안팎이라 크게 그리는
    자리에도 긴 변 1024 표시용 변형을 내보낸다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version = await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, content_type=content_type
    )
    asset = await _thumbnail_asset(db_session, version, content_type)
    asset.kind = kind
    asset.storage_key = storage_key.format(id=uuid.uuid4())
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}")

    assert resp.status_code == 200
    assert _url_key(resp.json()["thumbnailUrl"]) == build_display_key(asset.storage_key)


async def test_get_content_detail_thumbnail_url_is_null_without_a_thumbnail(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version = await _make_published_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    detail = await db_session.scalar(
        sa.select(CharacterVersionDetail).where(CharacterVersionDetail.content_version_id == version.id)
    )
    assert detail is not None
    detail.thumbnail_asset_id = None
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}")

    assert resp.status_code == 200
    assert resp.json()["thumbnailUrl"] is None


async def test_get_content_detail_thumbnail_url_is_identical_within_a_signing_window(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상세를 다시 받아도(모달 재오픈·채팅방 재진입) 같은 15분 구간이면 주소가 글자까지 같아 브라우저 캐시에서 바로
    그린다. 구간 경계를 넘으면 새 서명이라 바뀐다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version = await _make_published_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    async def thumbnail_url_at(at: datetime) -> str:
        _set_signing_clock(monkeypatch, at)
        resp = await db_client.get(f"/contents/{content.id}")
        assert resp.status_code == 200
        url: str = resp.json()["thumbnailUrl"]
        return url

    window_start = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    window_end = window_start + timedelta(minutes=15)
    first = await thumbnail_url_at(window_start + timedelta(seconds=1))
    last = await thumbnail_url_at(window_end - timedelta(seconds=1))
    next_window = await thumbnail_url_at(window_end)

    assert first == last
    assert next_window != last


async def test_get_content_detail_shows_placeholder_nickname_for_withdrawn_creator(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴 시 nickname을 파기하게 되면서
    드러난 회귀 — creator_nickname은 non-optional str이라 파기된 None을 그대로 넣으면
    Pydantic 검증에서 500이 난다(admin/contents.py의 선례와 같은 처방)."""
    creator = _make_user(nickname=None, deleted_at=datetime.now(UTC))
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, _version = await _make_published_content(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="탈퇴 작가의 캐릭터"
    )
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert resp.json()["creatorNickname"] == "(탈퇴한 사용자)"


async def test_get_content_detail_story_includes_ordered_starting_setups(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, version = await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, content_type=ContentType.STORY, name="스토리"
    )
    await _add_starting_setup(
        db_session, content_version_id=version.id, name="두번째", prologue="두번째 프롤로그", order=1
    )
    await _add_starting_setup(
        db_session, content_version_id=version.id, name="기본", prologue="기본 프롤로그", order=0
    )
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    setups = resp.json()["startingSetups"]
    assert [s["name"] for s in setups] == ["기본", "두번째"]
    assert setups[0]["prologue"] == "기본 프롤로그"


async def test_get_content_detail_access_status_reflects_visibility_and_moderation(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    private_content, _ = await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        visibility=ContentVisibility.PRIVATE,
        name="비공개",
    )
    restricted_content, _ = await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        moderation_status=ModerationStatus.RESTRICTED,
        name="이용제한",
    )
    deleted_content, _ = await _make_published_content(
        db_session,
        creator_user_id=user.id,
        genre_id=genre.id,
        moderation_status=ModerationStatus.DELETED,
        name="삭제됨",
    )
    await db_session.commit()

    private_resp = await db_client.get(f"/contents/{private_content.id}")
    assert private_resp.json()["accessStatus"] == {"kind": "accessible", "visibility": "private"}

    restricted_resp = await db_client.get(f"/contents/{restricted_content.id}")
    assert restricted_resp.json()["accessStatus"] == {"kind": "restricted", "visibility": None}

    deleted_resp = await db_client.get(f"/contents/{deleted_content.id}")
    assert deleted_resp.json()["accessStatus"] == {"kind": "deleted", "visibility": None}


async def test_get_content_detail_is_owner_true_only_for_creator(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, _ = await _make_published_content(db_session, creator_user_id=owner.id, genre_id=genre.id)
    await db_session.commit()

    anon_resp = await db_client.get(f"/contents/{content.id}")
    assert anon_resp.json()["isOwner"] is False

    await _login_as(db_client, other.id)
    other_resp = await db_client.get(f"/contents/{content.id}")
    assert other_resp.json()["isOwner"] is False

    await _login_as(db_client, owner.id)
    owner_resp = await db_client.get(f"/contents/{content.id}")
    assert owner_resp.json()["isOwner"] is True


async def test_get_content_detail_is_liked_reflects_viewers_own_like(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    liker = _make_user()
    other = _make_user()
    db_session.add_all([owner, liker, other])
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, _ = await _make_published_content(db_session, creator_user_id=owner.id, genre_id=genre.id)
    db_session.add(Like(user_id=liker.id, content_id=content.id))
    await db_session.commit()

    anon_resp = await db_client.get(f"/contents/{content.id}")
    assert anon_resp.json()["isLiked"] is False

    await _login_as(db_client, other.id)
    other_resp = await db_client.get(f"/contents/{content.id}")
    assert other_resp.json()["isLiked"] is False

    await _login_as(db_client, liker.id)
    liker_resp = await db_client.get(f"/contents/{content.id}")
    assert liker_resp.json()["isLiked"] is True


async def test_get_content_detail_is_favorited_reflects_viewers_own_favorite(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    favoriter = _make_user()
    other = _make_user()
    db_session.add_all([owner, favoriter, other])
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, _ = await _make_published_content(db_session, creator_user_id=owner.id, genre_id=genre.id)
    db_session.add(Favorite(user_id=favoriter.id, content_id=content.id))
    await db_session.commit()

    anon_resp = await db_client.get(f"/contents/{content.id}")
    assert anon_resp.json()["isFavorited"] is False

    await _login_as(db_client, other.id)
    other_resp = await db_client.get(f"/contents/{content.id}")
    assert other_resp.json()["isFavorited"] is False

    await _login_as(db_client, favoriter.id)
    favoriter_resp = await db_client.get(f"/contents/{content.id}")
    assert favoriter_resp.json()["isFavorited"] is True


async def test_get_content_detail_404_when_not_found_or_never_published(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    draft_content = Content(
        creator_user_id=user.id,
        type=ContentType.CHARACTER,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(draft_content)
    await db_session.flush()
    draft_version = ContentVersion(
        content_id=draft_content.id, version_number=None, published_at=None, detail_description="설명"
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

    missing_resp = await db_client.get(f"/contents/{uuid.uuid4()}")
    assert missing_resp.status_code == 404

    draft_resp = await db_client.get(f"/contents/{draft_content.id}")
    assert draft_resp.status_code == 404


async def test_list_content_versions_returns_only_published_ordered_desc(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)

    content, _ = await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, version_number=1
    )
    v2 = ContentVersion(
        content_id=content.id,
        version_number=2,
        published_at=datetime.now(UTC),
        detail_description="설명2",
    )
    db_session.add(v2)
    await db_session.flush()
    thumbnail = await _make_asset(db_session, user.id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=v2.id,
            name="이름v2",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    await db_session.flush()
    content.current_published_version_id = v2.id

    draft_version = ContentVersion(
        content_id=content.id, version_number=None, published_at=None, detail_description="초안"
    )
    db_session.add(draft_version)
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}/versions")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["versionNumber"] for item in body] == [2, 1]
    assert all("publishedAt" in item for item in body)


async def test_list_content_versions_404_when_content_not_found(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(f"/contents/{uuid.uuid4()}/versions")
    assert resp.status_code == 404


async def _view_count(db_session: AsyncSession, content_id: uuid.UUID) -> int:
    count = await db_session.scalar(sa.select(Content.view_count).where(Content.id == content_id))
    assert count is not None
    return count


async def _make_viewable_content(
    db_session: AsyncSession,
    *,
    visibility: ContentVisibility = ContentVisibility.PUBLIC,
    moderation_status: ModerationStatus = ModerationStatus.NORMAL,
) -> tuple[Content, User]:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _ = await _make_published_content(
        db_session,
        creator_user_id=creator.id,
        genre_id=genre.id,
        visibility=visibility,
        moderation_status=moderation_status,
    )
    await db_session.commit()
    return content, creator


async def test_view_count_increments_on_first_view(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session)

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    # ASGITransport awaits the whole app call including background tasks, so the
    # increment must already be visible here.
    assert await _view_count(db_session, content.id) == 1


async def test_view_count_deduped_for_same_viewer(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session)

    await db_client.get(f"/contents/{content.id}")
    await db_client.get(f"/contents/{content.id}")
    assert await _view_count(db_session, content.id) == 1


async def test_view_count_counts_distinct_guests_separately(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session)

    await db_client.get(f"/contents/{content.id}")
    db_client.cookies.clear()
    await db_client.get(f"/contents/{content.id}")
    assert await _view_count(db_session, content.id) == 2


async def test_view_count_counts_user_and_guest_separately(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session)
    viewer = _make_user()
    db_session.add(viewer)
    await db_session.commit()

    await db_client.get(f"/contents/{content.id}")
    assert await _view_count(db_session, content.id) == 1

    await _login_as(db_client, viewer.id)
    await db_client.get(f"/contents/{content.id}")
    assert await _view_count(db_session, content.id) == 2


async def test_view_count_not_incremented_for_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, creator = await _make_viewable_content(db_session)

    await _login_as(db_client, creator.id)
    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert await _view_count(db_session, content.id) == 0


async def test_view_count_not_incremented_for_private_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session, visibility=ContentVisibility.PRIVATE)

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert await _view_count(db_session, content.id) == 0


async def test_view_count_not_incremented_for_restricted_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(
        db_session, moderation_status=ModerationStatus.RESTRICTED
    )

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert await _view_count(db_session, content.id) == 0


async def test_view_count_not_incremented_for_deleted_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    content, _ = await _make_viewable_content(db_session, moderation_status=ModerationStatus.DELETED)

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert await _view_count(db_session, content.id) == 0


async def test_view_count_skipped_when_redis_errors(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    content, _ = await _make_viewable_content(db_session)

    async def _raise_redis_error(*args: object, **kwargs: object) -> None:
        raise RedisError("connection refused")

    monkeypatch.setattr(redis_client, "set", _raise_redis_error)

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert await _view_count(db_session, content.id) == 0


@pytest.mark.parametrize("content_type", [ContentType.STORY, ContentType.CHARACTER])
async def test_get_content_detail_returns_default_user_name_and_leaves_macros_in_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession, content_type: ContentType
) -> None:
    """작품 기본 이름은 보는 사람이 없는 곳(공유 미리보기)과 프로필 없는 사람의 화면이 `{{user}}` 를 바꿀 이름이다.
    글은 원문 그대로 보낸다 — 보는 사람의 프로필 이름이 먼저이고 그건 화면이 안다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version = await _make_published_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, content_type=content_type, one_liner="{{user}}의 하루"
    )
    detail: CharacterVersionDetail | StoryVersionDetail | None = (
        await db_session.get(CharacterVersionDetail, version.id)
        if content_type == ContentType.CHARACTER
        else await db_session.get(StoryVersionDetail, version.id)
    )
    assert detail is not None
    detail.default_user_name = "모험가"
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}")

    assert resp.status_code == 200
    assert resp.json()["defaultUserName"] == "모험가"
    assert resp.json()["oneLiner"] == "{{user}}의 하루"
