import uuid
from datetime import datetime, timezone, UTC

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import AdminUser, Asset, AssetKind, GuardianConsent, User, WithdrawnEmail
from factories import _make_user


async def test_user_and_asset_circular_reference(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    asset = Asset(owner_user_id=user.id, storage_key="profile/1.png", kind=AssetKind.ORIGINAL)
    db_session.add(asset)
    await db_session.flush()

    user.profile_image_asset_id = asset.id
    await db_session.flush()

    refreshed = await db_session.get(User, user.id)
    assert refreshed is not None
    assert refreshed.profile_image_asset_id == asset.id


async def test_user_google_sub_allows_multiple_nulls(db_session: AsyncSession) -> None:
    db_session.add(_make_user(google_sub=None))
    db_session.add(_make_user(google_sub=None))

    await db_session.flush()  # unique+nullable: two NULLs must not collide


async def test_guardian_consent_requires_existing_user(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    consent = GuardianConsent(
        user_id=user.id,
        guardian_name="보호자",
        guardian_contact="010-0000-0000",
        consent_agreed_at=datetime.now(UTC),
        ip_address="127.0.0.1",
    )
    db_session.add(consent)
    await db_session.flush()

    assert consent.id is not None


async def test_admin_user_is_a_separate_table_from_users(db_session: AsyncSession) -> None:
    email = f"admin-{uuid.uuid4()}@example.com"
    db_session.add(_make_user(email=email))
    db_session.add(AdminUser(email=email, password_hash="hashed"))

    await db_session.flush()  # same email across the two separate tables must be fine


# legal-revision-goal-prompt.md LR-7·LR-8. `alembic check`는 복합 PK는 비교하지만 단일
# 컬럼 PK의 유일성 자체는 실제 INSERT로만 확인된다(project_alembic_check_blind_spots와
# 같은 계열의 사각지대) — 같은 email_hmac을 두 번 넣으면 두 번째 flush가 IntegrityError로
# 거부돼야 재가입 차단(HMAC 조회)이 실제로 유일 키에 기대고 있다는 것이 증명된다.
async def test_withdrawn_email_rejects_duplicate_hmac(db_session: AsyncSession) -> None:
    email_hmac = "hmac-" + uuid.uuid4().hex

    db_session.add(WithdrawnEmail(email_hmac=email_hmac, withdrawn_at=datetime.now(UTC)))
    await db_session.flush()

    db_session.add(WithdrawnEmail(email_hmac=email_hmac, withdrawn_at=datetime.now(UTC)))
    with pytest.raises(IntegrityError):
        await db_session.flush()
