import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.content import ContentTarget, ContentType, ContentVisibility, ModerationStatus
from api.db.models.moderation import ReportReasonCategory
from api.db.models.story import EndingRuleOperator, LogicalOp, StoryPromptTemplate

VisibilityFilter = Literal["all", "public", "link", "private"]


class DraftSummary(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_asset_id: uuid.UUID | None
    thumbnail_url: str | None
    updated_at: datetime


class DraftListResponse(CamelModel):
    """`/me/drafts`의 커서 페이지네이션 봉투. `ContentListResponse`와 같은 모양이며 `/my`가 두
    엔드포인트를 같은 방식으로 소비할 수 있도록 항목 타입만 다르게 둔다."""

    items: list[DraftSummary]
    next_cursor: str | None


class ContentSummary(CamelModel):
    """`updated_at` is the current published version's `published_at`, not `Content.updated_at`
    (that column has no `onupdate`, so it never moves off the creation time)."""

    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_asset_id: uuid.UUID
    thumbnail_url: str | None
    view_count: int
    chat_count: int
    like_count: int
    visibility: ContentVisibility
    moderation_status: ModerationStatus
    updated_at: datetime


class ContentSummaryListResponse(CamelModel):
    """`/users/{id}/contents`의 커서 페이지네이션 봉투. `DraftListResponse`와 같은 모양."""

    items: list[ContentSummary]
    next_cursor: str | None


class UserProfileResponse(CamelModel):
    nickname: str
    bio: str | None
    profile_image_asset_id: uuid.UUID | None
    profile_image_url: str | None


class UpdateProfileRequest(CamelModel):
    nickname: str = Field(min_length=1)
    bio: str | None = None
    profile_image_asset_id: uuid.UUID | None = None


class GenreResponse(CamelModel):
    id: uuid.UUID
    name: str
    sort_order: int


class ContentListItem(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_url: str | None
    view_count: int
    creator_user_id: uuid.UUID
    creator_nickname: str


class ContentListResponse(CamelModel):
    items: list[ContentListItem]
    next_cursor: str | None


class StartingSetupSummary(CamelModel):
    id: uuid.UUID
    name: str
    prologue: str


AccessStatusKind = Literal["accessible", "restricted", "deleted"]


class ContentAccessStatus(CamelModel):
    """Mirrors techspec-content-versioning.md §1's `resolveAccessStatus` union:
    `visibility` is only meaningful when `kind == "accessible"`."""

    kind: AccessStatusKind
    visibility: ContentVisibility | None = None


class ContentDetailResponse(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    thumbnail_url: str | None
    creator_user_id: uuid.UUID
    creator_nickname: str
    genre_id: uuid.UUID
    genre_name: str
    hashtags: list[str]
    one_liner: str
    detail_description: str
    chat_count: int
    like_count: int
    is_liked: bool
    is_favorited: bool
    starting_setups: list[StartingSetupSummary] | None
    version_number: int
    updated_at: datetime
    access_status: ContentAccessStatus
    is_owner: bool


class ContentVersionSummary(CamelModel):
    version_number: int
    published_at: datetime


class ReportRequest(CamelModel):
    reason_category: ReportReasonCategory


class ContentCreateRequest(CamelModel):
    """techspec-backend-content.md §1.2."""

    type: Literal["character", "story"]


class ContentCreateResponse(CamelModel):
    content_id: uuid.UUID


class ExampleDialogueItem(CamelModel):
    id: str
    user_line: str
    character_line: str


class CharacterSituationalImageDraftInput(CamelModel):
    """`PATCH /contents/{id}/draft` payload item — only the fields this endpoint owns.
    `imageAssetId`/blurred variant are exclusively written by
    `POST /assets/{id}/register-situational-image` (US-071)."""

    id: uuid.UUID
    trigger_condition: str


class CharacterDraftPayload(CamelModel):
    name: str
    one_liner: str
    thumbnail_asset_id: uuid.UUID | None
    intro: str
    example_dialogues: list[ExampleDialogueItem]
    character_prompt: str
    playguide: str | None
    situational_images: list[CharacterSituationalImageDraftInput]
    description: str
    genre_id: uuid.UUID | None
    target: ContentTarget | None
    hashtags: list[str]
    visibility: ContentVisibility


class CharacterSituationalImageItem(CamelModel):
    id: uuid.UUID
    image_asset_id: uuid.UUID | None
    trigger_condition: str


class CharacterDraftResponse(CamelModel):
    id: uuid.UUID
    # Needed by the FE builder to call `POST /assets/{id}/register-situational-image`
    # (US-071), which is content_version_id-scoped and otherwise unreachable from this
    # response (`id` above is the content's physical id, not the draft version's).
    content_version_id: uuid.UUID
    type: Literal["character"] = "character"
    name: str
    one_liner: str
    thumbnail_asset_id: uuid.UUID | None
    intro: str
    example_dialogues: list[ExampleDialogueItem]
    character_prompt: str
    playguide: str | None
    situational_images: list[CharacterSituationalImageItem]
    description: str
    genre_id: uuid.UUID | None
    target: ContentTarget | None
    hashtags: list[str]
    visibility: ContentVisibility


class ContentPublishResponse(CamelModel):
    content_id: uuid.UUID
    version_number: int


class ContentVisibilityUpdateRequest(CamelModel):
    visibility: ContentVisibility


class StatDefDraftItem(CamelModel):
    id: uuid.UUID
    name: str
    icon: str
    color: str
    min_value: int
    max_value: int
    initial_value: int
    unit: str | None
    description: str
    # 매 턴 결정적으로 더해지는 값(감소는 음수). 채우면 그 스탯은 판정 LLM 대신 시스템이
    # 굴린다(`api.chat.stats.apply_stat_changes`) — "매 턴 반드시 1씩 줄어든다" 같은 카운터용.
    # 턴당 변화와 행동 반응이 섞인 스탯에는 쓰지 말 것(쓰면 LLM이 영영 못 건드린다).
    per_turn_delta: int | None = None


class EndingRuleDraftItem(CamelModel):
    """A single stat comparison. `stat_id` references a `StatDefDraftItem.id` (entity_id) —
    matches `EndingRule.stat_def_entity_id` (techspec-db-schema.md §5, §1 원칙 4: the chat
    runtime evaluates rules against a `stat_entity_id`-keyed value dict, so the reference is
    entity_id even though within one draft this is otherwise just a same-version reference)."""

    kind: Literal["rule"] = "rule"
    id: uuid.UUID
    stat_id: uuid.UUID
    operator: EndingRuleOperator
    threshold: float
    next_op: LogicalOp | None = None


class EndingRuleGroupDraftItem(CamelModel):
    """One level of nesting only (techspec-db-schema.md §5) — `rules` never contains groups."""

    kind: Literal["group"] = "group"
    id: uuid.UUID
    rules: list[EndingRuleDraftItem]
    next_op: LogicalOp | None = None


EndingRuleListDraftItem = Annotated[
    EndingRuleDraftItem | EndingRuleGroupDraftItem,
    Field(discriminator="kind"),
]


class EndingDraftItem(CamelModel):
    id: uuid.UUID
    name: str
    turn_count_gate: int
    judgment_prompt: str
    epilogue: str | None
    hint: str | None
    stat_rules: list[EndingRuleListDraftItem]


class StartingSetupDraftItem(CamelModel):
    id: uuid.UUID
    name: str
    prologue: str
    opening_message: str | None
    playguide: str | None
    suggested_replies: list[str]
    stat_defs: list[StatDefDraftItem]
    endings: list[EndingDraftItem]


class KeywordNoteDraftItem(CamelModel):
    id: uuid.UUID
    info_text: str
    trigger_keywords: list[str]
    starting_setup_id: uuid.UUID | None


class ShortcutDraftItem(CamelModel):
    id: uuid.UUID
    name: str
    description: str
    prompt: str


class StoryDraftPayload(CamelModel):
    name: str
    one_liner: str
    thumbnail_asset_id: uuid.UUID | None
    prompt_template: StoryPromptTemplate
    setting_text: str | None
    development_example: str | None
    custom_prompt: str | None
    starting_setups: list[StartingSetupDraftItem]
    keyword_notes: list[KeywordNoteDraftItem]
    shortcuts: list[ShortcutDraftItem]
    description: str
    genre_id: uuid.UUID | None
    target: ContentTarget | None
    hashtags: list[str]
    visibility: ContentVisibility


class StoryDraftResponse(CamelModel):
    id: uuid.UUID
    type: Literal["story"] = "story"
    name: str
    one_liner: str
    thumbnail_asset_id: uuid.UUID | None
    prompt_template: StoryPromptTemplate
    setting_text: str | None
    development_example: str | None
    custom_prompt: str | None
    starting_setups: list[StartingSetupDraftItem]
    keyword_notes: list[KeywordNoteDraftItem]
    shortcuts: list[ShortcutDraftItem]
    description: str
    genre_id: uuid.UUID | None
    target: ContentTarget | None
    hashtags: list[str]
    visibility: ContentVisibility
