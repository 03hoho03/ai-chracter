import uuid
from datetime import date, datetime, timedelta, timezone, UTC

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password
from api.db.models import (
    AdminActionLog,
    AdminUser,
    Asset,
    AssetKind,
    CharacterVersionDetail,
    ChatRoom,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationAction,
    ModerationStatus,
    Notification,
    User,
)
from api.db.models.story import StoryPromptTemplate, StoryVersionDetail


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(UTC),
        "privacy_agreed_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return User(**defaults)


async def _get_genre(db_session: AsyncSession) -> Genre:
    result = await db_session.execute(sa.select(Genre).limit(1))
    return result.scalars().one()


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


async def _create_admin(db_session: AsyncSession, **overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"admin-{uuid.uuid4()}@example.com",
        "password": "adminpassword123",
    }
    defaults.update(overrides)
    admin = AdminUser(
        email=str(defaults["email"]), password_hash=hash_password(str(defaults["password"]))
    )
    db_session.add(admin)
    await db_session.flush()
    return defaults


async def _login_as_admin(db_client: httpx.AsyncClient, payload: dict[str, object]) -> None:
    resp = await db_client.post(
        "/admin/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 204


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
    resp = await db_client.post("/dev/session-echo", json={"data": {"user_id": str(user.id)}})
    assert resp.status_code == 201

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
    resp = await db_client.post("/dev/session-echo", json={"data": {"user_id": str(user.id)}})
    assert resp.status_code == 201

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
    resp = await db_client.post("/dev/session-echo", json={"data": {"user_id": str(user.id)}})
    assert resp.status_code == 201

    resp = await db_client.post(
        f"/admin/contents/{uuid.uuid4()}/action",
        json={"action": "restrict", "reasonCategory": "spam"},
    )
    assert resp.status_code == 401


# ---- 목록 ------------------------------------------------------------------


async def test_content_without_any_report_appears_in_list(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """goal-prompt.md 2단계 핵심 검증 기준: 신고가 한 번도 없었던 작품도 목록에 뜬다."""
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
    대신 `admin_comment`가 필수다(goal-prompt.md §3-1, T-2/T-10)."""
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
    """goal-prompt.md 2단계 검증 기준: 직접 조치(신고 경유가 아님)에 대해서도 이의제기를
    넣으면 어드민 `/appeals`에 뜨고, 승인하면 콘텐츠가 복구된다 — §1-3이 명시한 대로
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
    session_resp = await db_client.post(
        "/dev/session-echo", json={"data": {"user_id": str(creator.id)}}
    )
    assert session_resp.status_code == 201

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
