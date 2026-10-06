import uuid
from datetime import date, datetime, timedelta, timezone, UTC

import boto3
import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.auth.verification import get_verification_code
from api.core import rate_limit
from api.core.config import settings
from api.core.redis import redis_client
from api.core.s3 import build_display_key, build_thumbnail_key, build_variant_keys, delete_object
from api.core.security import hash_withdrawn_email, verify_password
from api.db.models import (
    AdminActionLog,
    Asset,
    AssetKind,
    AssetStatus,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomMemorySnapshot,
    ChatRoomStat,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ImageGenerationRequest,
    Inquiry,
    InquiryCategory,
    InquiryStatus,
    ModerationStatus,
    Novel,
    NovelBatch,
    NovelChapter,
    NovelChapterRevision,
    NovelCharacter,
    NovelJob,
    NovelReadingPosition,
    NovelSnapshot,
    User,
    UserFeatureGrant,
    UserPersona,
    WithdrawnEmail,
)
from factories import (
    _add_media_book_cell,
    _create_admin,
    _get_genre,
    _grant_novelize,
    _login_as,
    _make_novel_tree,
    _plant_novel_extras,
    _make_user,
    _make_published_character,
    _make_published_story,
    _noting_open_transactions,
    _open_transaction_probe,
)


def _signup_payload(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "password": "password123",
        "nickname": "테스터",
        "birthDate": "2000-01-01",
        "termsAgreed": True,
        "privacyAgreed": True,
        "transferAgreed": True,
    }
    defaults.update(overrides)
    return defaults


async def _signup_and_login(db_client: httpx.AsyncClient, **overrides: object) -> dict[str, object]:
    payload = _signup_payload(**overrides)
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None

    verify_resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": stored["code"]}
    )
    assert verify_resp.status_code == 200

    login_resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login_resp.status_code == 204
    return payload


async def test_change_password_updates_hash_and_allows_relogin(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_login(db_client)

    resp = await db_client.patch(
        "/me/password",
        json={"currentPassword": payload["password"], "newPassword": "newpassword456"},
    )
    assert resp.status_code == 204

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    assert user.password_hash is not None
    assert await verify_password("newpassword456", user.password_hash)

    old_password_login = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert old_password_login.status_code == 401

    new_password_login = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": "newpassword456"}
    )
    assert new_password_login.status_code == 204


async def test_change_password_rejects_wrong_current_password(db_client: httpx.AsyncClient) -> None:
    await _signup_and_login(db_client)

    resp = await db_client.patch(
        "/me/password",
        json={"currentPassword": "wrong-password", "newPassword": "newpassword456"},
    )
    assert resp.status_code == 400


async def test_change_password_requires_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.patch(
        "/me/password",
        json={"currentPassword": "password123", "newPassword": "newpassword456"},
    )
    assert resp.status_code == 401


async def test_password_confirm_limit_is_shared_by_change_password_and_withdraw(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """비밀번호 변경과 탈퇴의 비밀번호 확인이 사용자당 한 통을 같이 쓴다 — 나뉘어 있으면 아래
    마지막 탈퇴는 자기 통의 절반만 쓴 상태라 통과한다."""
    payload = await _signup_and_login(db_client)
    half = rate_limit.PASSWORD_CONFIRM_USER_LIMIT // 2
    for _ in range(half):
        resp = await db_client.patch(
            "/me/password", json={"currentPassword": "wrong-password", "newPassword": "newpassword456"}
        )
        assert resp.status_code == 400
    for _ in range(rate_limit.PASSWORD_CONFIRM_USER_LIMIT - half):
        resp = await db_client.request("DELETE", "/me", json={"currentPassword": "wrong-password"})
        assert resp.status_code == 400

    withdraw = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert withdraw.status_code == 429
    detail = withdraw.json()["detail"]
    assert detail["code"] == "AUTH_LIMIT"
    assert detail["window"] == "auth"
    assert 0 < detail["retryAfterSeconds"] <= rate_limit.PASSWORD_CONFIRM_USER_WINDOW_SECONDS
    change = await db_client.patch(
        "/me/password", json={"currentPassword": payload["password"], "newPassword": "newpassword456"}
    )
    assert change.status_code == 429

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    assert user.deleted_at is None


async def test_withdraw_of_password_account_requires_current_password(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """누락(바디 없음·빈 바디)과 오답이 비밀번호 변경과 같은 400 이고, 어느 경우도 파기하지 않는다."""
    payload = await _signup_and_login(db_client)

    for resp in (
        await db_client.delete("/me"),
        await db_client.request("DELETE", "/me", json={}),
        await db_client.request("DELETE", "/me", json={"currentPassword": "wrong-password"}),
    ):
        assert resp.status_code == 400
        assert resp.json() == {"detail": "Current password is incorrect"}

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    assert user.deleted_at is None
    assert (await db_client.get("/me")).status_code == 200

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert resp.status_code == 204
    await db_session.refresh(user)
    assert user.deleted_at is not None


async def test_withdraw_of_social_account_needs_no_password_and_skips_the_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """소셜 전용 계정은 확인할 비밀번호가 없어 바디 없이 탈퇴하고, 비밀번호 확인 상한도 세지 않는다
    (통이 가득 차 있어도 막히지 않는다)."""
    user = _make_user(google_sub=f"google-sub-{uuid.uuid4()}")
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    await redis_client.set(f"rate_limit:password_confirm:{user.id}", 1000, ex=900)

    resp = await db_client.delete("/me")

    assert resp.status_code == 204
    await db_session.refresh(user)
    assert user.deleted_at is not None


async def test_withdraw_soft_deletes_hides_content_and_deletes_own_chat_rooms(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    genre = (await db_session.execute(sa.select(Genre).limit(1))).scalar_one()

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

    published_version = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(UTC),
        detail_description="설명",
    )
    draft_version = ContentVersion(
        content_id=content.id,
        version_number=None,
        published_at=None,
        detail_description="초안",
    )
    db_session.add_all([published_version, draft_version])
    await db_session.flush()

    own_room = ChatRoom(
        user_id=user.id, content_id=content.id, content_version_id=published_version.id
    )
    db_session.add(own_room)
    await db_session.flush()
    own_message = ChatMessage(chat_room_id=own_room.id, role=ChatMessageRole.USER, content="안녕하세요")
    db_session.add(own_message)
    db_session.add(
        ChatRoomStat(chat_room_id=own_room.id, stat_entity_id=uuid.uuid4(), current_value=1)
    )
    await db_session.flush()
    db_session.add(
        ChatRoomMemorySnapshot(
            chat_room_id=own_room.id,
            cursor_created_at=own_message.created_at,
            cursor_message_id=own_message.id,
            summary_text="요약",
            source="auto",
        )
    )

    other_user = User(
        email=f"viewer-{uuid.uuid4()}@example.com",
        nickname="뷰어",
        birth_date=date(2000, 1, 1),
        terms_agreed_at=datetime.now(UTC),
        privacy_agreed_at=datetime.now(UTC),
    )
    db_session.add(other_user)
    await db_session.flush()
    other_room = ChatRoom(
        user_id=other_user.id, content_id=content.id, content_version_id=published_version.id
    )
    db_session.add(other_room)
    await db_session.commit()

    own_room_id = own_room.id
    other_room_id = other_room.id
    content_id = content.id
    draft_version_id = draft_version.id

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert resp.status_code == 204

    reloaded_user = await db_session.scalar(select(User).where(User.id == user.id))
    assert reloaded_user is not None
    assert reloaded_user.deleted_at is not None

    reloaded_content = await db_session.get(Content, content_id)
    assert reloaded_content is not None
    assert reloaded_content.visibility == ContentVisibility.PRIVATE

    # The draft (unpublished) version is preserved, not deleted.
    assert await db_session.get(ContentVersion, draft_version_id) is not None

    assert await db_session.get(ChatRoom, own_room_id) is None
    remaining_messages = (
        await db_session.execute(
            select(ChatMessage).where(ChatMessage.chat_room_id == own_room_id)
        )
    ).scalars().all()
    assert remaining_messages == []
    remaining_stats = (
        await db_session.execute(
            select(ChatRoomStat).where(ChatRoomStat.chat_room_id == own_room_id)
        )
    ).scalars().all()
    assert remaining_stats == []
    remaining_snapshots = await db_session.scalar(
        select(sa.func.count())
        .select_from(ChatRoomMemorySnapshot)
        .where(ChatRoomMemorySnapshot.chat_room_id == own_room_id)
    )
    assert remaining_snapshots == 0

    # Another user's chat room against the same (now-private) content survives.
    assert await db_session.get(ChatRoom, other_room_id) is not None

    me_after = await db_client.get("/me")
    assert me_after.status_code == 401

    login_after = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login_after.status_code == 401


async def test_withdraw_requires_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.delete("/me")
    assert resp.status_code == 401


async def test_withdraw_purges_pii_and_records_withdrawn_email_hash(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴 시 평문 이메일이
    복원 불가능한 자리표시자로 바뀌고, 비밀번호 해시·닉네임·자기소개·생년월일·구글 식별자가
    파기되며, 재가입 차단용 HMAC 한 행이 withdrawn_emails에 남는다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    original_email = user.email
    user.google_sub = f"google-sub-{uuid.uuid4()}"
    user.bio = "안녕하세요"
    await db_session.commit()
    user_id = user.id

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert resp.status_code == 204

    reloaded = await db_session.get(User, user_id)
    assert reloaded is not None
    assert reloaded.deleted_at is not None
    assert reloaded.email == f"withdrawn:{user_id}"
    assert reloaded.password_hash is None
    assert reloaded.nickname is None
    assert reloaded.bio is None
    assert reloaded.birth_date is None
    assert reloaded.google_sub is None

    withdrawn_row = await db_session.scalar(
        select(WithdrawnEmail).where(
            WithdrawnEmail.email_hmac == hash_withdrawn_email(original_email)
        )
    )
    assert withdrawn_row is not None


async def test_withdraw_deletes_personas_referenced_by_default_and_rooms(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴하면 대화 프로필도 지운다. 기본 지정과 방 참조가
    둘 다 걸린 상태여야 "참조를 먼저 끊는 순서"가 검증된다(끊지 않으면 FK 위반으로 500)."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    user_id = user.id
    default = UserPersona(user_id=user_id, name="기본")
    other = UserPersona(user_id=user_id, name="다른")
    db_session.add_all([default, other])
    await db_session.flush()
    user.default_persona_id = default.id
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user_id, genre_id=genre.id)
    db_session.add(
        ChatRoom(
            user_id=user_id,
            content_id=content.id,
            content_version_id=content.current_published_version_id,
            persona_id=other.id,
        )
    )
    await db_session.commit()

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})

    assert resp.status_code == 204
    remaining = await db_session.scalar(
        select(sa.func.count()).select_from(UserPersona).where(UserPersona.user_id == user_id)
    )
    assert remaining == 0
    assert await db_session.scalar(select(User.default_persona_id).where(User.id == user_id)) is None


async def test_withdraw_with_admin_viewed_room_keeps_the_view_log_without_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """관리자가 열람한 방이 있어도 탈퇴는 끝까지 가야 한다. 열람 로그는 감사 기록이라 남고(유저
    상세의 조치 이력은 `target_user_id`로 계속 걸린다), 지워진 방을 가리키던 칸만 비운다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    user_id = user.id
    admin_id = uuid.UUID(str((await _create_admin(db_session))["id"]))
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user_id, genre_id=genre.id)
    room = ChatRoom(user_id=user_id, content_id=content.id, content_version_id=content.current_published_version_id)
    db_session.add(room)
    await db_session.flush()
    room_id = room.id
    await record_admin_action(
        db_session,
        admin_id=admin_id,
        action_type="chat-view",
        target_user_id=user_id,
        target_chat_room_id=room_id,
        reason_text="신고 확인",
    )
    await db_session.commit()

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})

    assert resp.status_code == 204
    assert await db_session.scalar(select(sa.func.count()).select_from(ChatRoom).where(ChatRoom.id == room_id)) == 0
    logs = (
        await db_session.execute(
            select(AdminActionLog.target_chat_room_id, AdminActionLog.target_user_id).where(
                AdminActionLog.admin_id == admin_id
            )
        )
    ).all()
    assert [tuple(row) for row in logs] == [(None, user_id)]


async def test_withdraw_deletes_profile_image_from_object_storage(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """프로필 이미지 R2 오브젝트도 탈퇴 시 지운다 —
    core/s3.py의 delete_object·assets/router.py의 호출 선례(:116,133,382)를 따른다.
    assets/router.py:124의 불변식(READY 이미지 asset은 항상 `_thumb.webp` 변형을 갖는다)에
    따라 원본과 함께 썸네일도 미리 업로드해두고, 탈퇴 후 둘 다 사라졌는지 확인한다 —
    썸네일을 안 지우면 이 검증 없이도 (지울 게 없어) 통과해버리는 항진명제가 된다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/profile-image/{uuid.uuid4()}.png",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    user.profile_image_asset_id = asset.id
    await db_session.commit()
    storage_key = asset.storage_key
    thumbnail_key = build_thumbnail_key(storage_key)
    user_id = user.id

    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=storage_key, Body=b"fake-profile-image")
    s3.put_object(Bucket=settings.s3_bucket_name, Key=thumbnail_key, Body=b"fake-thumbnail")
    s3.put_object(Bucket=settings.s3_bucket_name, Key=build_display_key(storage_key), Body=b"fake-display")

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert resp.status_code == 204

    # storage_key 확장자 이전까지가 원본·썸네일 공통 접두사다(build_thumbnail_key가
    # 확장자를 `_thumb.webp`로 바꿔 붙이므로).
    common_prefix = storage_key.rsplit(".", 1)[0]
    listed = s3.list_objects_v2(Bucket=settings.s3_bucket_name, Prefix=common_prefix)
    assert listed["KeyCount"] == 0

    reloaded = await db_session.get(User, user_id)
    assert reloaded is not None
    assert reloaded.profile_image_asset_id is None


async def test_signup_with_same_email_is_blocked_within_one_year_of_withdrawal(
    db_client: httpx.AsyncClient,
) -> None:
    """users.email 조회가 아니라 withdrawn_emails의
    HMAC 조회로 재가입을 막는다(탈퇴 시 email을 자리표시자로 바꾸므로 옛 방식은
    더 이상 작동하지 않는다)."""
    payload = await _signup_and_login(db_client)
    withdraw_resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert withdraw_resp.status_code == 204

    resp = await db_client.post("/auth/signup", json=_signup_payload(email=payload["email"]))
    assert resp.status_code == 409


async def test_signup_with_same_email_succeeds_after_withdrawn_block_period_expires(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """withdrawn_at + 1년이 지난 행은 조회 시점에
    무시된다(행 자체의 삭제는 백업 크론이 담당한다)."""
    payload = await _signup_and_login(db_client)
    withdraw_resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert withdraw_resp.status_code == 204

    withdrawn_row = await db_session.scalar(
        select(WithdrawnEmail).where(
            WithdrawnEmail.email_hmac == hash_withdrawn_email(str(payload["email"]))
        )
    )
    assert withdrawn_row is not None
    withdrawn_row.withdrawn_at = datetime.now(UTC) - timedelta(days=366)
    await db_session.commit()

    resp = await db_client.post("/auth/signup", json=_signup_payload(email=payload["email"]))
    assert resp.status_code == 201


async def test_verify_email_with_original_email_after_withdrawal_returns_400(
    db_client: httpx.AsyncClient,
) -> None:
    """탈퇴 후 users.email이 자리표시자로
    바뀌어 원래 이메일로는 이 조회가 더는 유저를 찾지 못한다 — 크래시가 아니라 '유저
    없음'과 같은 400이어야 한다(계정 존재 여부 비노출)."""
    payload = await _signup_and_login(db_client)
    withdraw_resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert withdraw_resp.status_code == 204

    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": "000000"}
    )
    assert resp.status_code == 400


async def test_verify_email_rejects_withdrawn_placeholder_email_format(
    db_client: httpx.AsyncClient,
) -> None:
    """자리표시자(withdrawn:{uuid})는 이메일
    형식이 아니라 EmailStr 검증에서 먼저 막힌다 — 이 값으로는 이 엔드포인트를 호출조차
    할 수 없다."""
    resp = await db_client.post(
        "/auth/verify-email", json={"email": f"withdrawn:{uuid.uuid4()}", "code": "000000"}
    )
    assert resp.status_code == 422


async def test_withdraw_deletes_unused_generated_asset_and_its_request_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """탈퇴한 유저의 미사용 GENERATED asset은
    S3 원본·썸네일과 함께 지워지고, 그 asset이 전부였던 요청 행도 같이 지워진다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    request = ImageGenerationRequest(
        owner_user_id=user.id,
        prompt="달빛 아래 고양이",
        style="anime",
        aspect_ratio="1:1",
        model="v1",
        requested_count=1,
        status="succeeded",
        completed_count=1,
    )
    db_session.add(request)
    await db_session.flush()

    asset_id = uuid.uuid4()
    storage_key = f"assets/generated/{asset_id}.png"
    asset = Asset(
        id=asset_id,
        owner_user_id=user.id,
        storage_key=storage_key,
        kind=AssetKind.GENERATED,
        status=AssetStatus.READY,
        request_id=request.id,
    )
    db_session.add(asset)
    await db_session.commit()
    request_id = request.id

    thumbnail_key = build_thumbnail_key(storage_key)
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=storage_key, Body=b"fake-generated-image")
    s3.put_object(Bucket=settings.s3_bucket_name, Key=thumbnail_key, Body=b"fake-thumbnail")
    s3.put_object(Bucket=settings.s3_bucket_name, Key=build_display_key(storage_key), Body=b"fake-display")

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert resp.status_code == 204

    assert await db_session.get(Asset, asset_id) is None
    assert await db_session.get(ImageGenerationRequest, request_id) is None

    common_prefix = storage_key.rsplit(".", 1)[0]
    listed = s3.list_objects_v2(Bucket=settings.s3_bucket_name, Prefix=common_prefix)
    assert listed["KeyCount"] == 0


async def test_withdraw_deletes_own_generated_asset_used_as_profile_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """`profile_image_asset_id = None` 대입(574줄)이 생성 이미지 파기
    블록보다 뒤로 옮겨지면, users.profile_image_asset_id가 여전히 이 asset을 참조한 채로
    `DELETE FROM assets`가 나가 FK 위반(IntegrityError)으로 탈퇴 전체가 500이 된다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/generated/{uuid.uuid4()}.png",
        kind=AssetKind.GENERATED,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    user.profile_image_asset_id = asset.id
    await db_session.commit()
    asset_id = asset.id

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert resp.status_code == 204

    assert await db_session.get(Asset, asset_id) is None


async def test_withdraw_keeps_generated_asset_used_as_content_thumbnail(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """콘텐츠 썸네일로 쓰이는 GENERATED asset은
    탈퇴해도 지우면 안 된다(발행 콘텐츠 썸네일이 깨지면 안 된다) — 그 요청 행도 남는다
    (asset이 남아 있으므로 "같은 수명"에 따라 요청 행도 같이 남아야 한다)."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    request = ImageGenerationRequest(
        owner_user_id=user.id,
        prompt="캐릭터 썸네일",
        style="anime",
        aspect_ratio="3:4",
        model="v1",
        requested_count=1,
        status="succeeded",
        completed_count=1,
    )
    db_session.add(request)
    await db_session.flush()

    asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/generated/{uuid.uuid4()}.png",
        kind=AssetKind.GENERATED,
        status=AssetStatus.READY,
        request_id=request.id,
    )
    db_session.add(asset)
    await db_session.flush()

    genre = (await db_session.execute(sa.select(Genre).limit(1))).scalar_one()
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

    version = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(UTC),
        detail_description="설명",
    )
    db_session.add(version)
    await db_session.flush()
    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="캐릭터",
            one_liner="",
            thumbnail_asset_id=asset.id,
            intro="",
            example_dialogues=[],
            character_prompt="",
        )
    )
    await db_session.commit()
    asset_id = asset.id
    request_id = request.id

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert resp.status_code == 204

    assert await db_session.get(Asset, asset_id) is not None
    assert await db_session.get(ImageGenerationRequest, request_id) is not None


async def test_withdraw_keeps_generated_asset_used_as_inquiry_attachment(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 collect_asset_usages는 문의 첨부
    (inquiries.attachment_asset_id)를 보지 않는다. 문의는 소유자만 검사하고 kind를 안
    보며(inquiry/router.py:42-51) 탈퇴해도 삭제되지 않으므로, 제외하지 않고 지우면 FK
    위반으로 탈퇴 트랜잭션 전체가 500으로 죽는다 — 이 테스트가 없으면 그 회귀를 아무도
    못 잡는다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/generated/{uuid.uuid4()}.png",
        kind=AssetKind.GENERATED,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()

    inquiry = Inquiry(
        user_id=user.id,
        category=InquiryCategory.BUG,
        title="문의 제목",
        body="문의 내용",
        attachment_asset_id=asset.id,
        status=InquiryStatus.PENDING,
    )
    db_session.add(inquiry)
    await db_session.commit()
    asset_id = asset.id
    inquiry_id = inquiry.id

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert resp.status_code == 204

    assert await db_session.get(Asset, asset_id) is not None
    assert await db_session.get(Inquiry, inquiry_id) is not None


async def test_withdraw_keeps_blocked_request_row_without_images(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이미지가 아예 없는 요청 행(차단·실패)은
    90일 파기 작업의 몫이라 탈퇴로는 건드리지 않는다 — 여기서 지우면 그 경계가 깨진다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    request = ImageGenerationRequest(
        owner_user_id=user.id,
        prompt="차단된 프롬프트",
        style="anime",
        aspect_ratio="1:1",
        model="v1",
        requested_count=1,
        status="blocked",
        blocked_count=1,
        blocked_reason="prompt",
    )
    db_session.add(request)
    await db_session.commit()
    request_id = request.id

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})
    assert resp.status_code == 204

    assert await db_session.get(ImageGenerationRequest, request_id) is not None


async def test_withdraw_deletes_generated_asset_that_a_kept_request_row_used_as_reference(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """차단된 요청 행은 탈퇴로 지우지 않지만(90일 파기 몫), 그 행이 참조로 가리키던 생성 이미지는
    지운다. 참조 FK 가 비우지 않으면 asset DELETE 가 FK 위반이 돼 탈퇴 전체가 500 이다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/generated/{uuid.uuid4()}.png",
        kind=AssetKind.GENERATED,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    request = ImageGenerationRequest(
        owner_user_id=user.id,
        prompt="참조가 막힌 요청",
        style="soft_portrait",
        aspect_ratio="1:1",
        model="v1",
        requested_count=1,
        status="blocked",
        blocked_count=1,
        blocked_reason="reference",
        reference_asset_id=asset.id,
    )
    db_session.add(request)
    await db_session.commit()
    asset_id = asset.id

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})

    assert resp.status_code == 204
    assert await db_session.get(Asset, asset_id) is None
    await db_session.refresh(request)
    assert request.reference_asset_id is None


async def test_withdraw_keeps_generated_asset_used_by_media_book_cell(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴는 쓰이지 않는 생성 이미지만 지운다. 미디어 북 칸이 쓰는 이미지를 사용처로 못 보면
    지우려다 칸 FK 에 걸려 탈퇴 전체가 500 이 된다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/generated/{uuid.uuid4()}.png",
        kind=AssetKind.GENERATED,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    assert story.current_published_version_id is not None
    await _add_media_book_cell(db_session, story.current_published_version_id, asset.id)
    await db_session.commit()
    asset_id = asset.id

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})

    assert resp.status_code == 204
    assert await db_session.get(Asset, asset_id) is not None


# ── 탈퇴가 저장소 삭제를 기다리는 동안 DB 트랜잭션을 쥐지 않는다 ──────────────────────────────
#
# 탈퇴는 회원이 가진 이미지 수에 비례해 저장소 삭제를 부르고(상한 없음), 그동안 회원 행과 댓글·좋아요를 단 남의 작품
# 행까지 잠근다. 그래서 지울 키만 모았다가 파기를 커밋한 뒤 응답 뒤에서 지운다(카카오 연결 끊기 알림과 같은 방식).
# 삭제가 실패하면 그 객체는 가리키는 행 없이 남는다 — 파기 기록·개인정보 삭제·재가입 차단은 이미 커밋돼 있다.


async def _withdrawing_user_with_images(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[dict[str, object], User, list[str]]:
    """프로필 이미지 하나와 쓰지 않은 생성 이미지 하나를 가진 가입자. 저장소에 원본·변형 키를 모두 올려 두고 그 키들을
    돌려준다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    profile = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/profile-image/{uuid.uuid4()}.png",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    generated = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/generated/{uuid.uuid4()}.png",
        kind=AssetKind.GENERATED,
        status=AssetStatus.READY,
    )
    db_session.add_all([profile, generated])
    await db_session.flush()
    user.profile_image_asset_id = profile.id
    await db_session.commit()
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    keys: list[str] = []
    for asset in (profile, generated):
        for key in (asset.storage_key, *build_variant_keys(asset.storage_key)):
            s3.put_object(Bucket=settings.s3_bucket_name, Key=key, Body=b"image")
            keys.append(key)
    return payload, user, keys


def _stored(keys: list[str]) -> list[str]:
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    present: list[str] = []
    for key in keys:
        listed = s3.list_objects_v2(Bucket=settings.s3_bucket_name, Prefix=key)
        if any(item["Key"] == key for item in listed.get("Contents", [])):
            present.append(key)
    return present


async def test_withdraw_deletes_stored_images_only_after_the_erase_is_committed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, _, keys = await _withdrawing_user_with_images(db_client, db_session)
    seen: list[tuple[str, int]] = []
    with _open_transaction_probe() as open_sessions:
        monkeypatch.setattr(
            "api.auth.withdrawal.delete_object",
            _noting_open_transactions(open_sessions, seen, "delete", delete_object),
        )
        resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})

    assert resp.status_code == 204
    assert seen == [("delete", 0)] * len(keys)
    assert _stored(keys) == []


@pytest.mark.usefixtures("committing_request_session")
async def test_failed_withdrawal_keeps_the_account_the_erase_record_and_the_stored_images(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 기준(결과를 보기 전에 적었다): 파기 도중(마지막 잔액 소멸에서) DB 오류가 나면 탈퇴는 하나도 남지 않아야
    한다 — 재가입 차단 기록이 생겼거나, 회원이 탈퇴 상태이거나, 저장소의 사진이 지워졌으면 실패다. 사용자는 다시
    누르면 된다."""
    payload, user, keys = await _withdrawing_user_with_images(db_client, db_session)

    async def broken_burn(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("burn failed")

    monkeypatch.setattr("api.auth.withdrawal.clover.burn_all", broken_burn)
    with pytest.raises(RuntimeError, match="burn failed"):
        await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})

    withdrawn = await db_session.scalar(
        select(WithdrawnEmail).where(WithdrawnEmail.email_hmac == hash_withdrawn_email(str(payload["email"])))
    )
    assert withdrawn is None
    deleted_at = await db_session.scalar(select(User.deleted_at).where(User.id == user.id))
    assert deleted_at is None
    assert _stored(keys) == keys


# ---- 허용 기능 목록 -------------------------------------------------------------


@pytest.mark.parametrize(
    ("enabled", "granted", "allowlisted", "expected"),
    [
        pytest.param(True, True, True, ["novelize"], id="enabled-granted-allowlisted"),
        pytest.param(False, True, True, [], id="kill-switch-off"),
        pytest.param(True, False, True, [], id="no-grant-row"),
        pytest.param(True, True, False, [], id="removed-from-allowlist"),
    ],
)
async def test_me_enabled_features_follow_the_route_gate(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    granted: bool,
    allowlisted: bool,
    expected: list[str],
) -> None:
    """FE 는 이 목록으로 진입점만 숨기므로 라우트 게이트와 같은 판정이어야 한다 — 어긋나면 보이는 진입점이 403 을
    받는다. 명단에서 빠진 경우는 허용 행이 남아 있어도 빈 목록이다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    if granted:
        await _grant_novelize(db_session, user.id)
    await db_session.commit()
    monkeypatch.setattr(settings, "novelize_enabled", enabled)
    monkeypatch.setattr(settings, "novelize_grant_allowlist", [user.id] if allowlisted else [uuid.uuid4()])
    await _login_as(db_client, user.id)

    resp = await db_client.get("/me")

    assert resp.status_code == 200
    assert resp.json()["enabledFeatures"] == expected


async def test_withdraw_erases_feature_grants(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    user_id = user.id
    await _grant_novelize(db_session, user_id)
    await db_session.commit()

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})

    assert resp.status_code == 204
    remaining = await db_session.scalar(
        select(sa.func.count()).select_from(UserFeatureGrant).where(UserFeatureGrant.user_id == user_id)
    )
    assert remaining == 0


async def test_withdraw_erases_novels_even_when_the_source_room_is_gone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """소설은 방과 따로 남는 문서라 방 파기에 딸려 지워지지 않는다 — 방이 이미 지워진 소설(`chat_room_id` NULL)까지
    탈퇴가 직접 파기해야 한다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    user_id = user.id
    tree = await _make_novel_tree(db_session, user_id)
    await _plant_novel_extras(db_session, tree)
    await db_session.commit()

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})

    assert resp.status_code == 204
    counts = [
        await db_session.scalar(select(sa.func.count()).select_from(Novel).where(Novel.user_id == user_id)),
        *[
            await db_session.scalar(select(sa.func.count()).select_from(model).where(column == tree.novel.id))
            for model, column in (
                (NovelBatch, NovelBatch.novel_id),
                (NovelCharacter, NovelCharacter.novel_id),
                (NovelSnapshot, NovelSnapshot.novel_id),
                (NovelReadingPosition, NovelReadingPosition.novel_id),
            )
        ],
        await db_session.scalar(
            select(sa.func.count()).select_from(NovelChapter).where(NovelChapter.id == tree.chapter.id)
        ),
        await db_session.scalar(
            select(sa.func.count())
            .select_from(NovelChapterRevision)
            .where(NovelChapterRevision.chapter_id == tree.chapter.id)
        ),
        await db_session.scalar(select(sa.func.count()).select_from(NovelJob).where(NovelJob.user_id == user_id)),
    ]
    assert counts == [0, 0, 0, 0, 0, 0, 0, 0]
