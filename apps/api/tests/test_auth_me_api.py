import uuid
from datetime import date, datetime, timedelta, timezone, UTC

import boto3
import httpx
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.verification import get_verification_code
from api.core.config import settings
from api.core.s3 import build_thumbnail_key
from api.core.security import hash_withdrawn_email, verify_password
from api.db.models import (
    Asset,
    AssetKind,
    AssetStatus,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
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
    User,
    WithdrawnEmail,
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
    assert verify_password("newpassword456", user.password_hash)

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
    db_session.add(
        ChatMessage(chat_room_id=own_room.id, role=ChatMessageRole.USER, content="안녕하세요")
    )
    db_session.add(
        ChatRoomStat(chat_room_id=own_room.id, stat_entity_id=uuid.uuid4(), current_value=1)
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

    resp = await db_client.delete("/me")
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
    """legal-revision-goal-prompt.md LR-6·LR-7·LR-8·LR-18·LR-20: 탈퇴 시 평문 이메일이
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

    resp = await db_client.delete("/me")
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


async def test_withdraw_deletes_profile_image_from_object_storage(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """legal-revision-goal-prompt.md LR-19: 프로필 이미지 R2 오브젝트도 탈퇴 시 지운다 —
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

    resp = await db_client.delete("/me")
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
    """legal-revision-goal-prompt.md LR-7: users.email 조회가 아니라 withdrawn_emails의
    HMAC 조회로 재가입을 막는다(LR-6이 탈퇴 시 email을 자리표시자로 바꾸므로 옛 방식은
    더 이상 작동하지 않는다)."""
    payload = await _signup_and_login(db_client)
    withdraw_resp = await db_client.delete("/me")
    assert withdraw_resp.status_code == 204

    resp = await db_client.post("/auth/signup", json=_signup_payload(email=payload["email"]))
    assert resp.status_code == 409


async def test_signup_with_same_email_succeeds_after_withdrawn_block_period_expires(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """legal-revision-goal-prompt.md LR-7: withdrawn_at + 1년이 지난 행은 조회 시점에
    무시된다(행 자체의 삭제는 백업 크론이 담당한다 — LR-32)."""
    payload = await _signup_and_login(db_client)
    withdraw_resp = await db_client.delete("/me")
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
    """legal-revision-goal-prompt.md LR-27 실측: 탈퇴 후 users.email이 자리표시자로
    바뀌어 원래 이메일로는 이 조회가 더는 유저를 찾지 못한다 — 크래시가 아니라 '유저
    없음'과 같은 400이어야 한다(E-12, 계정 존재 여부 비노출)."""
    payload = await _signup_and_login(db_client)
    withdraw_resp = await db_client.delete("/me")
    assert withdraw_resp.status_code == 204

    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": "000000"}
    )
    assert resp.status_code == 400


async def test_verify_email_rejects_withdrawn_placeholder_email_format(
    db_client: httpx.AsyncClient,
) -> None:
    """legal-revision-goal-prompt.md LR-27 실측: 자리표시자(withdrawn:{uuid})는 이메일
    형식이 아니라 EmailStr 검증에서 먼저 막힌다 — 이 값으로는 이 엔드포인트를 호출조차
    할 수 없다."""
    resp = await db_client.post(
        "/auth/verify-email", json={"email": f"withdrawn:{uuid.uuid4()}", "code": "000000"}
    )
    assert resp.status_code == 422


async def test_withdraw_deletes_unused_generated_asset_and_its_request_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """image-monitoring-goal-prompt.md IM-7: 탈퇴한 유저의 미사용 GENERATED asset은
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

    resp = await db_client.delete("/me")
    assert resp.status_code == 204

    assert await db_session.get(Asset, asset_id) is None
    assert await db_session.get(ImageGenerationRequest, request_id) is None

    common_prefix = storage_key.rsplit(".", 1)[0]
    listed = s3.list_objects_v2(Bucket=settings.s3_bucket_name, Prefix=common_prefix)
    assert listed["KeyCount"] == 0


async def test_withdraw_deletes_own_generated_asset_used_as_profile_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """T-4 적대적 리뷰: `profile_image_asset_id = None` 대입(574줄)이 생성 이미지 파기
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

    resp = await db_client.delete("/me")
    assert resp.status_code == 204

    assert await db_session.get(Asset, asset_id) is None


async def test_withdraw_keeps_generated_asset_used_as_content_thumbnail(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """image-monitoring-goal-prompt.md IM-7: 콘텐츠 썸네일로 쓰이는 GENERATED asset은
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

    resp = await db_client.delete("/me")
    assert resp.status_code == 204

    assert await db_session.get(Asset, asset_id) is not None
    assert await db_session.get(ImageGenerationRequest, request_id) is not None


async def test_withdraw_keeps_generated_asset_used_as_inquiry_attachment(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """image-monitoring-goal-prompt.md IM-7 (🔴): collect_asset_usages는 문의 첨부
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

    resp = await db_client.delete("/me")
    assert resp.status_code == 204

    assert await db_session.get(Asset, asset_id) is not None
    assert await db_session.get(Inquiry, inquiry_id) is not None


async def test_withdraw_keeps_blocked_request_row_without_images(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """image-monitoring-goal-prompt.md IM-7: 이미지가 아예 없는 요청 행(차단·실패)은
    IM-7a(90일 파기)의 몫이라 탈퇴로는 건드리지 않는다 — 여기서 지우면 그 경계가 깨진다."""
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

    resp = await db_client.delete("/me")
    assert resp.status_code == 204

    assert await db_session.get(ImageGenerationRequest, request_id) is not None
