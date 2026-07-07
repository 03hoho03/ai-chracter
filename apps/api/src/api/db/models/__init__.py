"""Import every model module so `Base.metadata` is fully populated for Alembic autogenerate."""

from api.db.models.auth import AdminUser, GuardianConsent, User
from api.db.models.character import CharacterVersionDetail, SituationalImage
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
    "CharacterVersionDetail",
    "Content",
    "ContentTarget",
    "ContentType",
    "ContentVersion",
    "ContentVisibility",
    "Genre",
    "GuardianConsent",
    "ModerationStatus",
    "SituationalImage",
    "User",
]
