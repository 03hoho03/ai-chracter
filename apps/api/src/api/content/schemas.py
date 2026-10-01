import unicodedata
import uuid
from collections.abc import Hashable, Iterable
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

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
    (that column has no `onupdate`, so it never moves off the creation time).

    `has_unpublished_changes` is the explicit `Content` flag, not something derived from the
    draft version's existence — publishing auto-clones a draft, so every published content has
    one."""

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
    has_unpublished_changes: bool
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
    """Mirrors the FE `resolveAccessStatus` union (`entities/content`):
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
    """Body of `POST /contents` — creates an empty draft."""

    type: Literal["character", "story"]


class ContentCreateResponse(CamelModel):
    content_id: uuid.UUID


class ExampleDialogueItem(CamelModel):
    id: str
    user_line: str
    character_line: str


class DevelopmentExampleItem(CamelModel):
    """`ExampleDialogueItem`의
    입출력 쌍 모양을 따르되 `id`는 두지 않는다 — 다른 레코드가 참조하는 대상이 아니고
    순서가 곧 정체성이다."""

    user_line: str
    assistant_line: str


class CharacterSituationalImageDraftInput(CamelModel):
    """`PATCH /contents/{id}/draft` payload item — only the fields this endpoint owns.
    `imageAssetId`/blurred variant are exclusively written by
    `POST /assets/{id}/register-situational-image`."""

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
    # which is content_version_id-scoped and otherwise unreachable from this
    # response (`id` above is the content's physical id, not the draft version's).
    content_version_id: uuid.UUID
    type: Literal["character"] = "character"
    name: str
    one_liner: str
    thumbnail_asset_id: uuid.UUID | None
    # Same S3 presigned URL as DraftSummary/_resolve_thumbnail_url,
    # not a new generation rule.
    thumbnail_url: str | None
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
    matches `EndingRule.stat_def_entity_id` (the chat
    runtime evaluates rules against a `stat_entity_id`-keyed value dict, so the reference is
    entity_id even though within one draft this is otherwise just a same-version reference)."""

    kind: Literal["rule"] = "rule"
    id: uuid.UUID
    stat_id: uuid.UUID
    operator: EndingRuleOperator
    threshold: float
    next_op: LogicalOp | None = None


class EndingRuleGroupDraftItem(CamelModel):
    """One level of nesting only — `rules` never contains groups."""

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


# 미디어 북 축 이름은 본문 태그 `{{img::인물/장면}}` 에서 이름으로 칸을 찾는 열쇠다. 앞뒤 공백과 유니코드
# 정규형(맥 파일명은 한글을 자모로 풀어 NFD 로 보낼 수 있다)이 다르면 화면에서 같은 이름이 다른 칸으로
# 갈라지므로, 저장 전에 하나로 맞춘다.
MEDIA_BOOK_NAME_MAX_LENGTH = 20
# 태그 문법의 구분자. 이름에 들어가면 태그를 인물·장면으로 가를 수 없다.
MEDIA_BOOK_NAME_FORBIDDEN_CHARACTERS = frozenset("/{}:")
MEDIA_BOOK_MAX_CELLS = 50


def _normalize_media_book_name(value: str) -> str:
    name = unicodedata.normalize("NFC", value.strip())
    if not 1 <= len(name) <= MEDIA_BOOK_NAME_MAX_LENGTH:
        raise ValueError(f"name must be 1-{MEDIA_BOOK_NAME_MAX_LENGTH} characters after trimming")
    if MEDIA_BOOK_NAME_FORBIDDEN_CHARACTERS & set(name):
        raise ValueError("name must not contain / { } :")
    return name


class MediaBookAxisInput(CamelModel):
    id: uuid.UUID
    name: Annotated[str, AfterValidator(_normalize_media_book_name)]


class MediaBookCellInput(CamelModel):
    """`person_id`·`scene_id` 는 같은 페이로드의 축 entity_id 다."""

    id: uuid.UUID
    person_id: uuid.UUID
    scene_id: uuid.UUID
    image_asset_id: uuid.UUID
    situation_description: str = Field(default="", max_length=100)
    unlock_hint: str = Field(default="", max_length=20)
    exclude_from_chat: bool = False


def _first_repeated(values: Iterable[Hashable]) -> Hashable | None:
    seen: set[Hashable] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


class MediaBookPayload(CamelModel):
    """페이로드 안에서 끝나는 검증만 여기서 한다(자산 소유·상태와 기존 칸의 자리는 DB 를 봐야 해서
    라우터가 한다). 이름 중복을 DB 제약이 아니라 여기서 막는 이유는 `MediaBookPerson` docstring."""

    people: list[MediaBookAxisInput]
    scenes: list[MediaBookAxisInput]
    cells: list[MediaBookCellInput]

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if len(self.cells) > MEDIA_BOOK_MAX_CELLS:
            raise ValueError(f"a media book holds at most {MEDIA_BOOK_MAX_CELLS} cells")
        for label, axis in (("person", self.people), ("scene", self.scenes)):
            if _first_repeated([item.id for item in axis]) is not None:
                raise ValueError(f"{label} ids must be unique")
            repeated_name = _first_repeated([item.name for item in axis])
            if repeated_name is not None:
                raise ValueError(f"{label} name is used twice: {repeated_name}")
        if _first_repeated([cell.id for cell in self.cells]) is not None:
            raise ValueError("cell ids must be unique")
        person_ids = {person.id for person in self.people}
        scene_ids = {scene.id for scene in self.scenes}
        for cell in self.cells:
            # 축 참조에는 FK 가 없어 여기서 막지 않으면 가리키는 축이 없는 칸이 저장된다.
            if cell.person_id not in person_ids or cell.scene_id not in scene_ids:
                raise ValueError("every cell must point at a person and a scene in this payload")
        if _first_repeated([(cell.person_id, cell.scene_id) for cell in self.cells]) is not None:
            raise ValueError("a person-scene position holds at most one cell")
        return self


class MediaBookAxisItem(CamelModel):
    id: uuid.UUID
    name: str


class MediaBookCellDraftItem(CamelModel):
    id: uuid.UUID
    person_id: uuid.UUID
    scene_id: uuid.UUID
    image_asset_id: uuid.UUID
    situation_description: str
    unlock_hint: str
    exclude_from_chat: bool
    # 칸 그리드는 원본이 필요 없어 썸네일 변형을 서명한다(`_resolve_thumbnail_url` 과 같은 규칙).
    image_url: str
    # 자산의 픽셀 크기. 모르는 자산(크기를 채우기 전이거나 원본을 못 읽은 자산)은 null 이다.
    image_width: int | None
    image_height: int | None


class MediaBookDraft(CamelModel):
    people: list[MediaBookAxisItem]
    scenes: list[MediaBookAxisItem]
    cells: list[MediaBookCellDraftItem]


class StoryDraftPayload(CamelModel):
    name: str
    one_liner: str
    thumbnail_asset_id: uuid.UUID | None
    prompt_template: StoryPromptTemplate
    setting_text: str | None
    # FE가 더 이상 이 필드를 폼에서 관리하지 않는다. 안 보내면(후속 리비전이
    # 컬럼을 드롭할 때까지) 롤백 안전망인 구 컬럼 값을 그대로 둬야 하므로, 값을 지우려는 명시적
    # `null`과 "안 보냄"을 구분해야 한다 — router.py가 `model_fields_set`으로 그 둘을 가른다.
    development_example: str | None = None
    custom_prompt: str | None
    # 필수화하지 않는다 — 기존 33건이 비어 있는 채로
    # 발행돼 있다. 시드도 이 기본값 덕에 JSON에 새 키를 추가하지 않고 통과한다.
    development_examples: list[DevelopmentExampleItem] = Field(default_factory=list)
    user_goal: str | None = None
    rules: str | None = None
    starting_setups: list[StartingSetupDraftItem]
    keyword_notes: list[KeywordNoteDraftItem]
    shortcuts: list[ShortcutDraftItem]
    description: str
    genre_id: uuid.UUID | None
    target: ContentTarget | None
    hashtags: list[str]
    visibility: ContentVisibility
    # 안 보내면(또는 null 이면) 미디어 북을 건드리지 않는다. 미디어 북을 모르는 화면(배포 전부터 열려
    # 있던 탭의 옛 번들)·시드도 이 저장 경로를 쓰므로, 빈 목록을 기본값으로 두면 그 저장 한 번이 칸을
    # 전부 지운다. 보냈을 때만 칸·축을 페이로드에 맞춘다 — 빈 목록이면 전부 지운다.
    media_book: MediaBookPayload | None = None


class StoryDraftResponse(CamelModel):
    id: uuid.UUID
    type: Literal["story"] = "story"
    name: str
    one_liner: str
    thumbnail_asset_id: uuid.UUID | None
    # Same S3 presigned URL as DraftSummary/_resolve_thumbnail_url,
    # not a new generation rule.
    thumbnail_url: str | None
    prompt_template: StoryPromptTemplate
    setting_text: str | None
    development_example: str | None
    custom_prompt: str | None
    development_examples: list[DevelopmentExampleItem]
    user_goal: str | None
    rules: str | None
    starting_setups: list[StartingSetupDraftItem]
    keyword_notes: list[KeywordNoteDraftItem]
    shortcuts: list[ShortcutDraftItem]
    description: str
    genre_id: uuid.UUID | None
    target: ContentTarget | None
    hashtags: list[str]
    visibility: ContentVisibility
    # 기본값은 응답을 옛 화면·생성 타입과 호환시키려는 것이고, 서버는 항상 채워 보낸다.
    media_book: MediaBookDraft = Field(default_factory=lambda: MediaBookDraft(people=[], scenes=[], cells=[]))
