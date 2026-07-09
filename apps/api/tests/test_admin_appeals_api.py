import uuid
from datetime import date, datetime, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password
from api.db.models import (
    AdminUser,
    Appeal,
    AppealStatus,
    AppealTargetKind,
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
    ModerationActionType,
    ModerationStatus,
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


async def _get_genre(db_session: AsyncSession) -> Genre:
    result = await db_session.execute(sa.select(Genre).limit(1))
    return result.scalars().one()


async def _make_published_character(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID, name: str = "캐릭터"
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.RESTRICTED,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(timezone.utc),
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

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _make_moderation_action(
    db_session: AsyncSession, *, content_id: uuid.UUID, admin_id: uuid.UUID
) -> ModerationAction:
    action = ModerationAction(content_id=content_id, admin_id=admin_id, action=ModerationActionType.RESTRICT)
    db_session.add(action)
    await db_session.flush()
    return action


async def _make_appeal(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    target_kind: AppealTargetKind,
    target_id: uuid.UUID,
    reason_text: str = "이의 있습니다.",
    status: AppealStatus = AppealStatus.PENDING,
) -> Appeal:
    appeal = Appeal(
        user_id=user_id,
        target_kind=target_kind,
        target_id=target_id,
        reason_text=reason_text,
        status=status,
    )
    db_session.add(appeal)
    await db_session.flush()
    return appeal


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
    return {**defaults, "id": admin.id}


async def _login_as_admin(db_client: httpx.AsyncClient, payload: dict[str, object]) -> None:
    resp = await db_client.post(
        "/admin/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 204


async def test_list_appeals_requires_admin_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/admin/appeals?page=1")
    assert resp.status_code == 401


async def test_list_appeals_returns_paginated_items(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    appeal_a = await _make_appeal(
        db_session,
        user_id=user.id,
        target_kind=AppealTargetKind.PUBLISH_REJECTION,
        target_id=uuid.uuid4(),
        reason_text="발행 거부가 부당합니다.",
    )
    appeal_b = await _make_appeal(
        db_session,
        user_id=user.id,
        target_kind=AppealTargetKind.MODERATION_ACTION,
        target_id=uuid.uuid4(),
        reason_text="조치가 부당합니다.",
        status=AppealStatus.RESOLVED,
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/appeals?page=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 1
    assert body["totalCount"] == 2
    assert body["totalPages"] == 1
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[str(appeal_a.id)]["targetKind"] == "publish-rejection"
    assert by_id[str(appeal_a.id)]["reasonText"] == "발행 거부가 부당합니다."
    assert by_id[str(appeal_a.id)]["status"] == "pending"
    assert by_id[str(appeal_a.id)]["verdict"] is None
    assert by_id[str(appeal_b.id)]["targetKind"] == "moderation-action"
    assert by_id[str(appeal_b.id)]["status"] == "resolved"


async def test_list_appeals_filters_by_status(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_appeal(
        db_session,
        user_id=user.id,
        target_kind=AppealTargetKind.PUBLISH_REJECTION,
        target_id=uuid.uuid4(),
        status=AppealStatus.PENDING,
    )
    await _make_appeal(
        db_session,
        user_id=user.id,
        target_kind=AppealTargetKind.PUBLISH_REJECTION,
        target_id=uuid.uuid4(),
        status=AppealStatus.RESOLVED,
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/appeals?page=1&status=resolved")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totalCount"] == 1
    assert all(item["status"] == "resolved" for item in body["items"])


async def test_resolve_appeal_requires_admin_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        f"/admin/appeals/{uuid.uuid4()}/resolve", json={"verdict": "rejected"}
    )
    assert resp.status_code == 401


async def test_resolve_appeal_unknown_id_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/appeals/{uuid.uuid4()}/resolve", json={"verdict": "rejected"}
    )
    assert resp.status_code == 404


async def test_resolve_appeal_rejected_updates_status_without_content_change(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    appeal = await _make_appeal(
        db_session,
        user_id=user.id,
        target_kind=AppealTargetKind.MODERATION_ACTION,
        target_id=character.id,
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/appeals/{appeal.id}/resolve", json={"verdict": "rejected"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["verdict"] == "rejected"

    await db_session.refresh(character)
    assert character.moderation_status == ModerationStatus.RESTRICTED


async def test_resolve_appeal_reprocessing_already_resolved_appeal_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    appeal = await _make_appeal(
        db_session,
        user_id=user.id,
        target_kind=AppealTargetKind.PUBLISH_REJECTION,
        target_id=uuid.uuid4(),
        status=AppealStatus.RESOLVED,
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/appeals/{appeal.id}/resolve", json={"verdict": "accepted"})
    assert resp.status_code == 400

    await db_session.refresh(appeal)
    assert appeal.status == AppealStatus.RESOLVED


async def test_resolve_appeal_accepted_publish_rejection_has_no_content_side_effect(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    appeal = await _make_appeal(
        db_session,
        user_id=user.id,
        target_kind=AppealTargetKind.PUBLISH_REJECTION,
        target_id=character.id,
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/appeals/{appeal.id}/resolve", json={"verdict": "accepted"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    assert resp.json()["verdict"] == "accepted"

    await db_session.refresh(character)
    assert character.moderation_status == ModerationStatus.RESTRICTED


async def test_resolve_appeal_accepted_moderation_action_unknown_target_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    appeal = await _make_appeal(
        db_session,
        user_id=user.id,
        target_kind=AppealTargetKind.MODERATION_ACTION,
        target_id=uuid.uuid4(),
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/appeals/{appeal.id}/resolve", json={"verdict": "accepted"})
    assert resp.status_code == 404

    await db_session.refresh(appeal)
    assert appeal.status == AppealStatus.PENDING


async def test_resolve_appeal_accepted_moderation_action_reverts_content_and_migrates_chat_rooms(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
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
        published_at=datetime.now(timezone.utc),
        detail_description="설명 v2",
    )
    db_session.add(new_version)
    await db_session.flush()
    character.current_published_version_id = new_version.id

    room = ChatRoom(user_id=chatter.id, content_id=character.id, content_version_id=old_version_id)
    db_session.add(room)

    admin_payload = await _create_admin(db_session)
    await db_session.flush()
    action = await _make_moderation_action(
        db_session, content_id=character.id, admin_id=uuid.UUID(str(admin_payload["id"]))
    )
    appeal = await _make_appeal(
        db_session,
        user_id=creator.id,
        target_kind=AppealTargetKind.MODERATION_ACTION,
        target_id=action.id,
    )
    await db_session.commit()

    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(f"/admin/appeals/{appeal.id}/resolve", json={"verdict": "accepted"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["verdict"] == "accepted"

    await db_session.refresh(character)
    assert character.moderation_status == ModerationStatus.NORMAL

    await db_session.refresh(room)
    assert room.content_version_id == new_version.id
    assert room.version_auto_upgraded is True
