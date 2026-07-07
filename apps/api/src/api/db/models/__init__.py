"""Import every model module so `Base.metadata` is fully populated for Alembic autogenerate."""

from api.db.models.auth import AdminUser, GuardianConsent, User
from api.db.models.media import Asset, AssetKind

__all__ = ["AdminUser", "Asset", "AssetKind", "GuardianConsent", "User"]
