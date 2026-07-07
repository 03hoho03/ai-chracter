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
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
    EndingRuleOperator,
    KeywordNote,
    LogicalOp,
    Shortcut,
    StartingSetup,
    StatDef,
    StoryPromptTemplate,
    StoryVersionDetail,
)

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
    "Ending",
    "EndingRule",
    "EndingRuleGroup",
    "EndingRuleOperator",
    "Genre",
    "GuardianConsent",
    "KeywordNote",
    "LogicalOp",
    "ModerationStatus",
    "Shortcut",
    "SituationalImage",
    "StartingSetup",
    "StatDef",
    "StoryPromptTemplate",
    "StoryVersionDetail",
    "User",
]
