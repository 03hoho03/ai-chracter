import uuid
from datetime import datetime, timezone, UTC

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import AdminUser, Asset, AssetKind, GuardianConsent, User
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
