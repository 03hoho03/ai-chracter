"""Import every model module so `Base.metadata` is fully populated for Alembic autogenerate."""

from api.db.models.auth import AdminUser, GuardianConsent, User
from api.db.models.content import (
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetKind

__all__ = [
    "AdminUser",
    "Asset",
    "AssetKind",
    "Content",
    "ContentTarget",
    "ContentType",
    "ContentVersion",
    "ContentVisibility",
    "Genre",
    "GuardianConsent",
    "ModerationStatus",
    "User",
]
