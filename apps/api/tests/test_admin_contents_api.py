import uuid
from datetime import datetime, timedelta, timezone, UTC
from urllib.parse import urlparse

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    AdminActionLog,
    Asset,
    AssetKind,
    AssetStatus,
    CharacterVersionDetail,
    ChatRoom,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationAction,
    ModerationStatus,
    Notification,
)
from api.core.s3 import build_thumbnail_key
from api.db.models.character import SituationalImage
from api.db.models.story import StoryPromptTemplate, StoryVersionDetail
from factories import _add_named_media_cell, _create_admin, _get_genre, _login_as, _login_as_admin, _make_user


async def _make_published_character(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    genre_id: uuid.UUID,
    name: str = "캐릭터",
    view_count: int = 0,
    chat_count: int = 0,
    created_at: datetime | None = None,
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
        view_count=view_count,
        chat_count=chat_count,
    )
    if created_at is not None:
        content.created_at = created_at
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(UTC),
        detail_description="설명입니다",
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = Asset(
        owner_user_id=creator_user_id, storage_key=f"assets/test/{uuid.uuid4()}", kind=AssetKind.ORIGINAL
    )
    db_session.add(thumbnail)
    await db_session.flush()

    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name=name,
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="캐릭터 프롬프트",
        )
    )
    await db_session.flush()

    # ⚠️ 발행을 흉내내는 헬퍼는 반드시 이 포인터까지 세팅해야 한다 — 안 하면 "발행됨"
    # 판정이 전부 통과하는데도 아무것도 검증하지 않는다(이 저장소의 알려진 함정).
    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _make_published_story(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    genre_id: uuid.UUID,
    name: str = "스토리",
    view_count: int = 0,
    chat_count: int = 0,
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.STORY,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
        view_count=view_count,
        chat_count=chat_count,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(UTC),
        detail_description="스토리 설명",
    )
    db_session.add(version)
    await db_session.flush()

    db_session.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name=name,
            one_liner="한줄소개",
            thumbnail_asset_id=None,
            prompt_template=StoryPromptTemplate.CUSTOM,
            setting_text=None,
            development_example=None,
            custom_prompt="커스텀 프롬프트",
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _make_draft_only_character(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID
) -> Content:
    """발행 버전이 없는(초안만 있는) 작품 — `current_published_version_id`가 null이다."""
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PRIVATE,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id,
        version_number=None,
        published_at=None,
        detail_description="",
    )
    db_session.add(version)
    await db_session.flush()

    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="초안캐릭터",
            one_liner="",
            thumbnail_asset_id=None,
            intro="",
            example_dialogues=[],
            character_prompt="",
        )
    )
    await db_session.flush()
    return content


# ---- 인증 ----------------------------------------------------------------


async def test_list_contents_requires_admin_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/admin/contents?page=1")
    assert resp.status_code == 401


async def test_regular_user_session_cannot_list_contents(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    # 세션이 실제로 섰음을 먼저 고정한다 —
    # 안 그러면 세션이 아예 안 서도 초록이라 위 무세션 401 테스트와 같은 명제가 된다.
    assert (await db_client.get("/me")).status_code == 200

    resp = await db_client.get("/admin/contents?page=1")
    assert resp.status_code == 401


async def test_content_detail_requires_admin_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(f"/admin/contents/{uuid.uuid4()}")
    assert resp.status_code == 401


async def test_regular_user_session_cannot_view_content_detail(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    assert (await db_client.get("/me")).status_code == 200

    resp = await db_client.get(f"/admin/contents/{uuid.uuid4()}")
    assert resp.status_code == 401


async def test_content_action_requires_admin_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        f"/admin/contents/{uuid.uuid4()}/action",
        json={"action": "restrict", "reasonCategory": "spam"},
    )
    assert resp.status_code == 401


async def test_regular_user_session_cannot_act_on_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    assert (await db_client.get("/me")).status_code == 200

    resp = await db_client.post(
        f"/admin/contents/{uuid.uuid4()}/action",
        json={"action": "restrict", "reasonCategory": "spam"},
    )
    assert resp.status_code == 401


# ---- 목록 ------------------------------------------------------------------


async def test_content_without_any_report_appears_in_list(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """신고가 한 번도 없었던 작품도 목록에 뜬다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/contents?page=1")
    assert resp.status_code == 200
    body = resp.json()
    assert str(character.id) in {item["id"] for item in body["items"]}


async def test_draft_only_content_appears_in_list_without_q(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """초안만 있고 발행 버전이 없는 작품도 `q` 없이 목록에 떠야 한다(outer join)."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    draft = await _make_draft_only_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/contents?page=1")
    assert resp.status_code == 200
    body = resp.json()
    by_id = {item["id"]: item for item in body["items"]}
    assert str(draft.id) in by_id
    assert by_id[str(draft.id)]["name"] == ""


async def test_draft_only_content_excluded_when_q_given(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    draft = await _make_draft_only_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/contents?page=1&q=초안")
    assert resp.status_code == 200
    body = resp.json()
    assert str(draft.id) not in {item["id"] for item in body["items"]}


async def test_content_list_filters_by_type(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    story = await _make_published_story(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/contents?page=1&type=story")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(story.id) in ids
    assert str(character.id) not in ids


async def test_content_list_filters_by_visibility(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    public_content = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id
    )
    private_content = await _make_draft_only_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id
    )
    private_content.visibility = ContentVisibility.PRIVATE
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/contents?page=1&visibility=private")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(private_content.id) in ids
    assert str(public_content.id) not in ids


async def test_content_list_filters_by_moderation_status(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    normal_content = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id
    )
    restricted_content = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id
    )
    restricted_content.moderation_status = ModerationStatus.RESTRICTED
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/contents?page=1&moderationStatus=restricted")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(restricted_content.id) in ids
    assert str(normal_content.id) not in ids


async def test_content_list_q_matches_character_and_story_case_insensitive(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="Sparkle Cat"
    )
    story = await _make_published_story(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="sparkle saga"
    )
    other = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="상관없음"
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/contents?page=1&q=SPARKLE")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(character.id) in ids
    assert str(story.id) in ids
    assert str(other.id) not in ids


async def test_content_list_sort_by_views_and_chats_change_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    low = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, view_count=1, chat_count=100
    )
    high = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, view_count=100, chat_count=1
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/contents?page=1&sort=views")
    ids_by_views = [item["id"] for item in resp.json()["items"]]
    assert ids_by_views.index(str(high.id)) < ids_by_views.index(str(low.id))

    resp = await db_client.get("/admin/contents?page=1&sort=chats")
    ids_by_chats = [item["id"] for item in resp.json()["items"]]
    assert ids_by_chats.index(str(low.id)) < ids_by_chats.index(str(high.id))


async def test_content_list_sort_is_deterministic_on_ties(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """동점(view_count 동일)이어도 두 번 호출한 순서가 완전히 같아야 한다 — 흔들리면
    offset 페이지네이션에서 행이 중복/누락된다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    for _ in range(5):
        await _make_published_character(
            db_session, creator_user_id=creator.id, genre_id=genre.id, view_count=5
        )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp1 = await db_client.get("/admin/contents?page=1&sort=views")
    resp2 = await db_client.get("/admin/contents?page=1&sort=views")
    ids1 = [item["id"] for item in resp1.json()["items"]]
    ids2 = [item["id"] for item in resp2.json()["items"]]
    assert ids1 == ids2


async def test_content_list_pagination_second_page_has_no_duplicate_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    for i in range(25):
        await _make_published_character(
            db_session,
            creator_user_id=creator.id,
            genre_id=genre.id,
            created_at=datetime.now(UTC) - timedelta(minutes=i),
        )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp1 = await db_client.get("/admin/contents?page=1")
    resp2 = await db_client.get("/admin/contents?page=2")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    body1 = resp1.json()
    body2 = resp2.json()
    assert body1["totalCount"] == 25
    assert body1["totalPages"] == 2
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert len(ids1) == 20
    assert len(ids2) == 5
    assert ids1.isdisjoint(ids2)


# ---- 상세 --------------------------------------------------------------


async def test_content_detail_unknown_id_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/contents/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_content_detail_returns_prompt_versions_and_creator_for_character(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user(nickname="제작자")
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="캐릭터E"
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/contents/{character.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(character.id)
    assert body["name"] == "캐릭터E"
    assert body["prompt"] == "캐릭터 프롬프트"
    assert body["hasUnpublishedChanges"] is False
    assert body["thumbnailUrl"] is not None
    assert body["creator"]["id"] == str(creator.id)
    assert body["creator"]["email"] == creator.email
    assert body["creator"]["nickname"] == "제작자"
    assert len(body["versions"]) == 1
    assert body["versions"][0]["isDraft"] is False
    assert body["versions"][0]["versionNumber"] == 1
    assert body["versions"][0]["name"] == "캐릭터E"


async def test_content_detail_shows_placeholder_nickname_for_withdrawn_creator(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user(nickname=None, deleted_at=datetime.now(UTC))
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="캐릭터F"
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/contents/{character.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["creator"]["nickname"] == "(탈퇴한 사용자)"


async def test_content_detail_uses_custom_prompt_for_story(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(
        db_session, creator_user_id=creator.id, genre_id=genre.id, name="스토리F"
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/contents/{story.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "story"
    assert body["prompt"] == "커스텀 프롬프트"
    assert body["thumbnailUrl"] is None


def _url_key(url: str) -> str:
    """서명 URL 이 가리키는 객체 키(경로에서 버킷 이름을 뗀 나머지)."""
    return urlparse(url).path.split("/", 2)[2]


async def _ready_asset(db_session: AsyncSession, owner_user_id: uuid.UUID, prefix: str) -> Asset:
    asset = Asset(
        owner_user_id=owner_user_id,
        storage_key=f"assets/{prefix}/{uuid.uuid4()}.webp",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


async def _add_draft_version(db_session: AsyncSession, content: Content) -> ContentVersion:
    """발행본 위에 열린 편집 중 초안. 초안에만 있는 그림이 상세에 섞이지 않는지 보려고 쓴다."""
    draft = ContentVersion(content_id=content.id, version_number=None, published_at=None, detail_description="")
    db_session.add(draft)
    await db_session.flush()
    return draft


async def test_content_detail_lists_published_character_images_in_builder_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    assert character.current_published_version_id is not None
    detail = await db_session.get(CharacterVersionDetail, character.current_published_version_id)
    assert detail is not None
    thumbnail = await db_session.get(Asset, detail.thumbnail_asset_id)
    assert thumbnail is not None

    # 빌더 순서와 반대로 넣는다 — 순서를 안 정하면 넣은 순서대로 나와 라벨이 뒤바뀐다.
    second = await _ready_asset(db_session, creator.id, "situational-image")
    first = await _ready_asset(db_session, creator.id, "situational-image")
    first_blurred = await _ready_asset(db_session, creator.id, "situational-image")
    db_session.add(
        SituationalImage(
            entity_id=uuid.uuid4(),
            content_version_id=character.current_published_version_id,
            image_asset_id=second.id,
            trigger_condition="두 번째",
            order=1,
        )
    )
    await db_session.flush()
    db_session.add(
        SituationalImage(
            entity_id=uuid.uuid4(),
            content_version_id=character.current_published_version_id,
            image_asset_id=first.id,
            blurred_asset_id=first_blurred.id,
            trigger_condition="첫 번째",
            order=0,
        )
    )
    draft = await _add_draft_version(db_session, character)
    draft_only = await _ready_asset(db_session, creator.id, "situational-image")
    db_session.add(
        SituationalImage(
            entity_id=uuid.uuid4(),
            content_version_id=draft.id,
            image_asset_id=draft_only.id,
            trigger_condition="초안에만",
            order=0,
        )
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/contents/{character.id}")
    assert resp.status_code == 200
    images = resp.json()["publishedImages"]
    assert [image["label"] for image in images] == ["대표 이미지", "상황 이미지 1", "상황 이미지 2"]
    # 원본은 블러본이 아니라 작가가 올린 그림이다.
    assert [_url_key(image["imageUrl"]) for image in images] == [
        thumbnail.storage_key,
        first.storage_key,
        second.storage_key,
    ]
    assert [_url_key(image["thumbnailUrl"]) for image in images] == [
        build_thumbnail_key(thumbnail.storage_key),
        build_thumbnail_key(first.storage_key),
        build_thumbnail_key(second.storage_key),
    ]


async def test_content_detail_lists_published_story_media_book_cells_person_then_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=creator.id, genre_id=genre.id)
    version_id = story.current_published_version_id
    assert version_id is not None

    # 축은 넣은 순서가 축 순서다(민아 → 서준, 교실 → 옥상). 칸은 그 순서와 다르게 넣는다.
    mina_class, mina_class_asset = await _add_named_media_cell(db_session, version_id, creator.id, "민아", "교실")
    _, seojun_roof_asset = await _add_named_media_cell(db_session, version_id, creator.id, "서준", "옥상")
    _, mina_roof_asset = await _add_named_media_cell(db_session, version_id, creator.id, "민아", "옥상")
    _, seojun_class_asset = await _add_named_media_cell(db_session, version_id, creator.id, "서준", "교실")
    blurred = await _ready_asset(db_session, creator.id, "media-book-blur")
    mina_class.blurred_asset_id = blurred.id
    draft = await _add_draft_version(db_session, story)
    await _add_named_media_cell(db_session, draft.id, creator.id, "초안인물", "초안장면")
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/contents/{story.id}")
    assert resp.status_code == 200
    images = resp.json()["publishedImages"]
    assert [image["label"] for image in images] == [
        "미디어 북 민아·교실",
        "미디어 북 민아·옥상",
        "미디어 북 서준·교실",
        "미디어 북 서준·옥상",
    ]
    expected_keys = [
        mina_class_asset.storage_key,
        mina_roof_asset.storage_key,
        seojun_class_asset.storage_key,
        seojun_roof_asset.storage_key,
    ]
    assert [_url_key(image["imageUrl"]) for image in images] == expected_keys
    assert [_url_key(image["thumbnailUrl"]) for image in images] == [build_thumbnail_key(key) for key in expected_keys]


async def test_content_detail_has_no_published_images_for_draft_only_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_draft_only_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    draft_id = await db_session.scalar(sa.select(ContentVersion.id).where(ContentVersion.content_id == content.id))
    assert draft_id is not None
    draft_detail = await db_session.get(CharacterVersionDetail, draft_id)
    assert draft_detail is not None
    draft_detail.thumbnail_asset_id = (await _ready_asset(db_session, creator.id, "thumbnail")).id
    db_session.add(
        SituationalImage(
            entity_id=uuid.uuid4(),
            content_version_id=draft_id,
            image_asset_id=(await _ready_asset(db_session, creator.id, "situational-image")).id,
            trigger_condition="초안에만",
            order=0,
        )
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/contents/{content.id}")
    assert resp.status_code == 200
    assert resp.json()["publishedImages"] == []


# ---- 조치 --------------------------------------------------------------


async def test_content_action_unknown_content_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/contents/{uuid.uuid4()}/action",
        json={"action": "restrict", "reasonCategory": "spam"},
    )
    assert resp.status_code == 404


async def test_content_action_restrict_updates_status_notifies_and_logs(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/contents/{character.id}/action",
        json={"action": "restrict", "reasonCategory": "hate", "adminComment": "직접 조치입니다"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["moderationStatus"] == "restricted"

    actions = (
        await db_session.scalars(
            sa.select(ModerationAction).where(ModerationAction.content_id == character.id)
        )
    ).all()
    assert len(actions) == 1

    notifications = (
        await db_session.scalars(sa.select(Notification).where(Notification.content_id == character.id))
    ).all()
    assert len(notifications) == 1
    assert notifications[0].reason_category == "hate"
    assert notifications[0].admin_comment == "직접 조치입니다"
    assert notifications[0].action_id == actions[0].id

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_content_id == character.id)
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].action_type == "content-restrict"
    assert logs[0].reason_category == "hate"


async def test_content_action_missing_reason_category_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/contents/{character.id}/action", json={"action": "restrict"}
    )
    assert resp.status_code == 422


async def test_content_action_reject_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/contents/{character.id}/action",
        json={"action": "reject", "reasonCategory": "spam"},
    )
    assert resp.status_code == 400


async def test_content_action_lift_restriction_requires_restricted_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/contents/{character.id}/action",
        json={"action": "lift-restriction", "reasonCategory": "spam"},
    )
    assert resp.status_code == 400


async def test_content_action_lift_restriction_restores_normal(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    character.moderation_status = ModerationStatus.RESTRICTED
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/contents/{character.id}/action",
        json={"action": "lift-restriction", "adminComment": "정상화합니다"},
    )
    assert resp.status_code == 200
    assert resp.json()["moderationStatus"] == "normal"

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_content_id == character.id)
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].action_type == "content-lift"


async def test_content_action_lift_restriction_missing_admin_comment_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`lift-restriction`은 `Notification`을 만들지 않아 `reasonCategory`를 요구하지 않지만,
    대신 `admin_comment`가 필수다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    character.moderation_status = ModerationStatus.RESTRICTED
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/contents/{character.id}/action", json={"action": "lift-restriction"}
    )
    assert resp.status_code == 422


async def test_content_action_lift_restriction_blank_admin_comment_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    character.moderation_status = ModerationStatus.RESTRICTED
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/contents/{character.id}/action",
        json={"action": "lift-restriction", "adminComment": "   "},
    )
    assert resp.status_code == 422


async def test_content_action_lift_restriction_migrates_chat_rooms_to_latest_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`lift-restriction`이 호출하는 `upgrade_content_chat_rooms_to_latest_version`의 부수효과 —
    기존에는 신고 경유 케이스(`test_admin_appeals_api.py`)에만 이 검증이 있었다."""
    creator = _make_user()
    chatter = _make_user()
    db_session.add_all([creator, chatter])
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    old_version_id = character.current_published_version_id
    assert old_version_id is not None

    new_version = ContentVersion(
        content_id=character.id,
        version_number=2,
        published_at=datetime.now(UTC),
        detail_description="설명 v2",
    )
    db_session.add(new_version)
    await db_session.flush()
    character.current_published_version_id = new_version.id
    character.moderation_status = ModerationStatus.RESTRICTED

    room = ChatRoom(user_id=chatter.id, content_id=character.id, content_version_id=old_version_id)
    db_session.add(room)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/contents/{character.id}/action",
        json={"action": "lift-restriction", "adminComment": "해제합니다"},
    )
    assert resp.status_code == 200
    assert resp.json()["moderationStatus"] == "normal"

    await db_session.refresh(room)
    assert room.content_version_id == new_version.id
    assert room.version_auto_upgraded is True


async def test_direct_action_appeal_round_trip_restores_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """직접 조치(신고 경유가 아님)에 대해서도 이의제기를
    넣으면 어드민 `/appeals`에 뜨고, 승인하면 콘텐츠가 복구된다 —
    `AppealTargetKind.MODERATION_ACTION` 경로를 신고 경유 조치와 구분 없이 재사용해야 한다."""
    creator = _make_user()
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    # 1. 신고 없이 직접 restrict
    action_resp = await db_client.post(
        f"/admin/contents/{character.id}/action",
        json={"action": "restrict", "reasonCategory": "hate", "adminComment": "직접 조치입니다"},
    )
    assert action_resp.status_code == 200
    assert action_resp.json()["moderationStatus"] == "restricted"

    actions = (
        await db_session.scalars(
            sa.select(ModerationAction).where(ModerationAction.content_id == character.id)
        )
    ).all()
    assert len(actions) == 1
    action_id = actions[0].id

    # 2. 제작자 세션(어드민 세션과 쿠키 이름이 달라 공존한다)으로 이의제기
    await _login_as(db_client, creator.id)

    appeal_resp = await db_client.post(
        "/appeals",
        json={
            "targetKind": "moderation-action",
            "targetId": str(action_id),
            "reasonText": "부당한 조치입니다.",
        },
    )
    assert appeal_resp.status_code == 201
    appeal_id = appeal_resp.json()["appealId"]

    # 3. 어드민 `/appeals` 목록에 뜨는지 확인
    list_resp = await db_client.get("/admin/appeals?page=1")
    assert list_resp.status_code == 200
    by_id = {item["id"]: item for item in list_resp.json()["items"]}
    assert appeal_id in by_id
    assert by_id[appeal_id]["targetKind"] == "moderation-action"

    # 4. 승인 처리 → 콘텐츠가 normal로 복구
    resolve_resp = await db_client.post(
        f"/admin/appeals/{appeal_id}/resolve", json={"verdict": "accepted"}
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "resolved"

    await db_session.refresh(character)
    assert character.moderation_status == ModerationStatus.NORMAL
