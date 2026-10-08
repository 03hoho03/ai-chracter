import unicodedata
import uuid
from collections.abc import Hashable, Iterable
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, StringConstraints, TypeAdapter, model_validator

from api.chat.keyword_notes import normalize_keyword_text
from api.content.author_macros import default_user_name_error
from api.core.schema import CamelModel
from api.db.models.content import ContentTarget, ContentType, ContentVisibility, ModerationStatus
from api.db.models.moderation import ReportReasonCategory
from api.db.models.story import EndingRuleOperator, LogicalOp, StatChangeDirection, StoryPromptTemplate
from api.persona.schemas import PERSONA_NAME_MAX_LENGTH

VisibilityFilter = Literal["all", "public", "link", "private"]


def _reject_invalid_default_user_name(value: str) -> str:
    error = default_user_name_error(value)
    if error is not None:
        raise ValueError(error)
    return value


# 작품 기본 이름. 대화 프로필 이름 대신 같은 `{{user}}` 자리에 들어가므로 상한도 프로필 이름과 같다. 비우면 대체어를
# 쓴다는 뜻이라 빈 값을 받는다. 요청에만 건다 — 응답에 걸면 규칙이 바뀐 뒤 이미 저장된 값이 있는 초안을 열 수 없다.
DefaultUserName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=PERSONA_NAME_MAX_LENGTH),
    AfterValidator(_reject_invalid_default_user_name),
]


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


class HomeCurationItem(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    one_liner: str
    # 이 발행본의 작품 기본 이름(빈 값 = 대체어). 응답은 보는 사람과 무관하므로 화면이 보는 사람의 프로필 이름을 먼저
    # 쓰고, 없을 때 이 값으로 한줄소개의 `{{user}}` 를 바꾼다. 기본값은 이 필드를 모르는 생성 타입·화면과의 호환용이다.
    default_user_name: str = Field(default_factory=str)
    thumbnail_url: str | None


class HomeCurationResponse(CamelModel):
    """`item` 이 null 이면 그 유형은 지정이 없거나 지정 작품이 지금 공개 목록에 없다 — 홈은 섹션을 그리지 않는다.
    본문 자체를 null 로 내지 않고 감싸는 이유는 "지정 없음" 을 빈 응답과 헷갈리지 않게 하려는 것이다."""

    item: HomeCurationItem | None


class StartingSetupSummary(CamelModel):
    id: uuid.UUID
    name: str
    prologue: str


class MediaTagImage(CamelModel):
    """글 속 칸 id 형태 태그(`{{img::<칸 id>}}`)가 가리키는 그림. 응답은 `{칸 id: MediaTagImage}` 맵으로
    싣고, 맵에 없는 칸(지워졌거나 버전에 없는 칸)의 태그는 화면이 빈칸으로 둔다.

    `url` 은 원본 서명 URL 이다(대화 중 상황 이미지와 같다). `width`·`height` 는 자산의 픽셀 크기로 화면이
    그림이 오기 전에 높이를 잡는 데 쓰고, 크기를 모르는 자산이면 null 이다."""

    url: str
    width: int | None
    height: int | None


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
    # 현재 발행본의 작품 기본 이름(빈 값 = 대체어). 글 속 `{{user}}` 는 바꾸지 않고 내보낸다 — 보는 사람의 프로필
    # 이름이 먼저이고 그건 화면이 안다. 공유 미리보기처럼 보는 사람이 없는 곳이 이 값을 쓴다.
    default_user_name: str = Field(default_factory=str)
    chat_count: int
    like_count: int
    is_liked: bool
    is_favorited: bool
    starting_setups: list[StartingSetupSummary] | None
    # 등록 설명·프롤로그의 미디어 북 태그는 칸 id 형태로 바꿔 내보내고, 그 칸들의 그림을 여기 싣는다
    # (현재 발행본 기준). 기본값을 둬 생성 타입에서 선택 필드가 되게 한다 — 이 필드를 모르는 화면은 그대로 돈다.
    media_tag_images: dict[uuid.UUID, MediaTagImage] = Field(default_factory=dict)
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
    # 안 보내면 저장된 값을 그대로 둔다(router 가 `model_fields_set` 으로 가른다) — 이 칸을 모르는 화면(배포 전부터
    # 열려 있던 탭의 옛 번들)의 자동저장이 작가가 넣은 이름을 지우지 않게. `default_factory` 인 이유는
    # `KeywordNoteDraftInput` 의 같은 주석과 같다.
    default_user_name: DefaultUserName = Field(default_factory=str)
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
    default_user_name: str
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


def _both_directions() -> StatChangeDirection:
    return "both"


class StatRuleDraftItem(CamelModel):
    """스탯 하나의 「조건 → ±n」 규칙. 배열 순서가 `order` 라 순서 필드는 따로 없다. 조건은 앞뒤 공백을 떼어 저장한다.

    개수·글자 수 상한과 폭 0·id 중복 금지는 요청에만 건다(`StoryDraftPayload` 의 검증) — 이 타입은 초안 응답에도
    쓰이므로, 여기에 걸면 상한을 바꾼 뒤 이미 저장된 규칙이 있는 초안을 열 수 없다(GET 500). 폭이 스탯 범위 폭을
    넘는지는 발행이 본다."""

    id: uuid.UUID
    condition: Annotated[str, AfterValidator(str.strip)]
    delta: int


class StatDefDraftItem(CamelModel):
    """스탯 하나. 저장 요청·초안 응답·미리보기 세션이 함께 쓴다.

    `change_direction`·`max_change_per_turn` 은 안 보내면 기존 스탯의 값을 그대로 둔다(router 가 `model_fields_set`
    으로 가른다). 이 옵션을 모르는 화면(배포 전부터 열려 있던 탭의 옛 번들)의 자동저장이 작가가 건 제약을 지우지 않게
    하려는 것이다. 새 스탯은 기본값(양방향·제한 없음)으로 들어간다. 기본값을 `default_factory` 로 두는 이유는
    `KeywordNoteDraftInput` 의 같은 주석과 같다. 턴당 변화와 함께 쓰거나 폭을 0 이하로 둔 값도 저장은 받는다 —
    여기서 막으면 그 초안의 자동저장이 편집마다 실패하므로 발행(`validate_story_publish`)이 막는다."""

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
    # 판정 LLM 이 낸 값을 코드가 자르는 두 옵션(`api.chat.stats.apply_stat_changes`). 폭은 턴 시작 값에서 잰다.
    change_direction: StatChangeDirection = Field(default_factory=_both_directions)
    max_change_per_turn: int | None = Field(default_factory=lambda: None)
    # 안 보내면 기존 스탯의 규칙을 건드리지 않는다(router 가 `model_fields_set` 으로 가른다). 규칙을 모르는 화면(배포
    # 전부터 열려 있던 탭의 옛 번들)·이 키를 적지 않은 시드는 보내지 않으므로, 빈 목록과 같게 다루면 그 저장 한 번이
    # 작가가 쓴 규칙을 전부 지운다. 보냈을 때만 페이로드에 맞춘다 — 빈 목록이면 전부 지운다.
    rules: list[StatRuleDraftItem] = Field(default_factory=list)


# 생략하면 기존 스탯의 값을 그대로 두는 필드들(`StatDefDraftItem` docstring).
STAT_DEF_OPTION_FIELDS = frozenset({"change_direction", "max_change_per_turn"})


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
    """`priority_stat_id` 는 같은 턴에 규칙을 통과한 엔딩이 여럿일 때 비교할 스탯이다(같은 시작설정 `StatDefDraftItem.id`,
    비우면 목록 순서 자리에서 판정). 안 보내면 기존 엔딩의 값을 그대로 둔다(router 가 `model_fields_set` 으로 가른다) —
    이 칸을 모르는 화면(배포 전부터 열려 있던 탭의 옛 번들)의 자동저장이 작가가 고른 값을 지우지 않게 하려는 것이다.
    지우려면 `null` 을 보낸다. 기본값을 `default_factory` 로 두는 이유는 `KeywordNoteDraftInput` 의 같은 주석과 같다."""

    id: uuid.UUID
    name: str
    turn_count_gate: int
    judgment_prompt: str
    epilogue: str | None
    hint: str | None
    stat_rules: list[EndingRuleListDraftItem]
    priority_stat_id: uuid.UUID | None = Field(default_factory=lambda: None)


class SituationNoteDraftItem(CamelModel):
    """상황 노트 하나. 저장 요청·초안 응답·미리보기 세션이 함께 쓴다. 배열 순서가 `order`(조건이 참인 노트가 위에서부터
    실린다)라 순서 필드는 따로 없다.

    조건은 엔딩의 스탯 규칙과 같은 타입을 쓴다 — 같은 시작설정의 스탯을 entity_id 로 가리킨다. 상한(개수·길이·규칙 수)은
    요청에만 건다(`StoryDraftPayload` 의 검증). 이 타입은 응답에도 쓰이므로 여기에 걸면, 나중에 상한을 낮추거나 손으로
    넣은 행이 상한을 넘을 때 그 초안을 열 수 없다(GET 500).

    조건이 없거나 본문이 빈 노트도 저장은 받는다. 빌더가 "노트 추가" 직후의 빈 노트를 그대로 자동저장하므로 여기서 막으면
    노트를 추가할 때마다 자동저장이 멈춘다 — 그 검사는 발행(`validate_story_publish`)이 한다."""

    id: uuid.UUID
    name: str
    info_text: str
    condition_rules: list[EndingRuleListDraftItem]


class StartingSetupDraftItem(CamelModel):
    """`situation_notes` 는 안 보내면 그 시작설정의 상황 노트를 건드리지 않는다(router 가 `model_fields_set` 으로
    가른다). 상황 노트를 모르는 화면(배포 전부터 열려 있던 탭의 옛 번들)·이 필드를 적지 않은 시드는 보내지 않으므로, 빈 목록과
    같게 다루면 그 저장 한 번이 다른 탭에서 만든 노트를 전부 지운다. 보냈을 때만 페이로드에 맞춘다 — 빈 목록이면 전부
    지운다. 기본값을 `default_factory` 로 두는 이유는 `KeywordNoteDraftInput` 의 같은 주석과 같다."""

    id: uuid.UUID
    name: str
    prologue: str
    opening_message: str | None
    playguide: str | None
    suggested_replies: list[str]
    stat_defs: list[StatDefDraftItem]
    endings: list[EndingDraftItem]
    situation_notes: list[SituationNoteDraftItem] = Field(default_factory=list)


# 상황 노트 저장 상한(시작설정마다). 빌더가 입력 단계에서 같은 상한을 지켜야 하는 이유는 아래 키워드북 상한 주석과 같다.
# 본문이 참인 턴마다 전부 실리므로 개수와 길이를 함께 묶는다. 규칙 수는 그룹 안의 규칙까지 센다(그룹 자체는 세지 않는다).
MAX_SITUATION_NOTES_PER_SETUP = 10
SITUATION_NOTE_MAX_INFO_LENGTH = 800
SITUATION_NOTE_MAX_NAME_LENGTH = 20
SITUATION_NOTE_MAX_RULES = 10

# 스탯 규칙 저장 상한(스탯마다). 빌더가 입력 단계에서 같은 상한을 지켜야 하는 이유는 아래 키워드북 상한 주석과 같다.
# 규칙 목록은 판정 프롬프트에 스탯마다 실리므로 개수와 조건 길이를 함께 묶는다. 조건 길이는 앞뒤 공백을 뗀 뒤의 코드
# 포인트 수다.
MAX_STAT_RULES_PER_STAT = 10
STAT_RULE_MAX_CONDITION_LENGTH = 100


# 상황 노트의 조건은 JSONB 한 칸에 `model_dump(mode="json")` 꼴로 저장한다(UUID·enum 이 문자열이 된다). 읽는 쪽은 이것으로
# 다시 규칙 타입으로 되돌린다.
RULE_LIST_ADAPTER = TypeAdapter(list[EndingRuleListDraftItem])


def count_rules(items: Iterable[EndingRuleDraftItem | EndingRuleGroupDraftItem]) -> int:
    """규칙 목록의 규칙 개수 — 그룹은 그 안의 규칙 수로 센다."""
    return sum(len(item.rules) if isinstance(item, EndingRuleGroupDraftItem) else 1 for item in items)


# 키워드북 저장 상한. 빌더 자동저장은 폼 검증 없이 폼 값을 그대로 보내므로, 빌더가 입력 단계에서 같은 상한을 지켜야
# 한다(`apps/web` `features/build-story/model/schema.ts` 의 키워드북 상수) — 여기가 더 엄격하면 그 초안의 자동저장이
# 통째로 멈춘다.
# 길이는 보낸 글자 그대로의 코드 포인트 수다(빌더도 그렇게 센다). NFC 로 바꾼 뒤 재면 길어지는 문자가 있어 빌더가
# 받아 준 값을 여기서 거절하게 된다.
KEYWORD_NOTE_MAX_INFO_LENGTH = 800
KEYWORD_NOTE_MAX_KEYWORDS = 10
KEYWORD_NOTE_MAX_KEYWORD_LENGTH = 20
KEYWORD_NOTE_MAX_NAME_LENGTH = 20
KEYWORD_NOTE_MAX_STICKY_TURNS = 5
MAX_KEYWORD_NOTES = 50
MAX_ALWAYS_ON_KEYWORD_NOTES = 3


def _check_keywords(keywords: list[str]) -> list[str]:
    """공백은 거의 모든 글에 들어 있어 공백뿐인 키워드는 키워드 구실을 못 한다. 매칭이 같게 보는 두 키워드(대소문자·
    유니코드 조합만 다른 것)는 매칭을 바꾸지 않으면서 노트당 개수 상한의 한 자리를 차지한다. 저장하는 값은 바꾸지
    않는다."""
    seen: set[str] = set()
    for keyword in keywords:
        if not keyword.strip():
            raise ValueError("keywords must not be blank")
        key = normalize_keyword_text(keyword)
        if key in seen:
            raise ValueError(f"keyword is used twice ignoring case: {keyword}")
        seen.add(key)
    return keywords


KeywordList = Annotated[
    list[Annotated[str, Field(max_length=KEYWORD_NOTE_MAX_KEYWORD_LENGTH)]],
    Field(max_length=KEYWORD_NOTE_MAX_KEYWORDS),
    AfterValidator(_check_keywords),
]


class KeywordNoteDraftInput(CamelModel):
    """저장 요청의 노트 하나. 상한은 요청에만 건다 — 응답(`KeywordNoteDraftItem`)에 걸면 상한이 생기기 전에 저장됐거나
    서버를 이전 버전으로 되돌린 사이 저장된 행이 있는 초안을 열 수 없다(GET 500).

    키워드가 하나도 없거나 정보가 빈 노트는 받아 준다. 빌더가 "노트 추가" 직후의 빈 노트를 그대로 자동저장하므로
    여기서 막으면 노트를 추가할 때마다 자동저장이 멈춘다 — 그 검사는 발행(`validate_story_publish`)이 한다.

    `name`·`exclude_keywords`·`sticky_turns`·`always_on` 은 안 보내면 기존 노트의 값을 그대로 둔다(router 가
    `model_fields_set` 으로 가른다). 이 옵션을 모르는 화면(배포 전부터 열려 있던 탭의 옛 번들)의 자동저장이 작가가 켠
    값을 기본값으로 되돌리지 않게 하려는 것이다. 새 노트는 기본값으로 들어간다."""

    id: uuid.UUID
    info_text: str = Field(max_length=KEYWORD_NOTE_MAX_INFO_LENGTH)
    trigger_keywords: KeywordList
    starting_setup_id: uuid.UUID | None
    # 아래 옵션의 기본값은 `default=` 가 아니라 `default_factory` 로 둔다. OpenAPI 에 `default` 가 찍히면 FE 생성
    # 타입(openapi-typescript)이 그 필드를 필수로 만들어 화면이 기본값을 명시해 보내게 되고, 그러면 그 화면이 옛 번들로
    # 남았을 때 "생략 = 기존 값 유지"가 깨진다.
    # 목록에서 노트를 알아보게 하는 이름이라 앞뒤 공백은 의미가 없다. 길이는 빌더처럼 보낸 그대로 잰다.
    name: Annotated[str, Field(max_length=KEYWORD_NOTE_MAX_NAME_LENGTH), AfterValidator(str.strip)] = Field(
        default_factory=str
    )
    # 상시 노트도 받는다 — 금지 키워드가 나온 턴에는 상시 노트도 빠진다.
    exclude_keywords: KeywordList = Field(default_factory=list)
    sticky_turns: int = Field(default_factory=int, ge=0, le=KEYWORD_NOTE_MAX_STICKY_TURNS)
    always_on: bool = Field(default_factory=bool)


# 생략하면 기존 노트의 값을 그대로 두는 필드들(`KeywordNoteDraftInput` docstring).
KEYWORD_NOTE_OPTION_FIELDS = frozenset({"name", "exclude_keywords", "sticky_turns", "always_on"})


class KeywordNoteDraftItem(CamelModel):
    """초안 응답의 노트 하나. 배열 순서가 `order`(위가 먼저 실린다)라 순서 필드는 따로 없다. 서버는 새 필드를 항상
    채워 보낸다. 기본값은 그 필드가 생기기 전에 만든 FE 타입·픽스처와의 호환용이라 생성 타입에서 선택 필드로 남게
    `default_factory` 로 둔다(`KeywordNoteDraftInput` 의 같은 주석)."""

    id: uuid.UUID
    info_text: str
    trigger_keywords: list[str]
    starting_setup_id: uuid.UUID | None
    name: str = Field(default_factory=str)
    exclude_keywords: list[str] = Field(default_factory=list)
    sticky_turns: int = Field(default_factory=int)
    always_on: bool = Field(default_factory=bool)


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
    # `CharacterDraftPayload.default_user_name` 과 같다.
    default_user_name: DefaultUserName = Field(default_factory=str)
    starting_setups: list[StartingSetupDraftItem]
    keyword_notes: list[KeywordNoteDraftInput] = Field(max_length=MAX_KEYWORD_NOTES)
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

    @model_validator(mode="after")
    def _check_always_on_count(self) -> Self:
        # 상시 노트는 매 턴 키워드 발동 노트와 따로 실린다. 개수를 저장에서 막아 두면 대화 중에는 자르지 않아도 된다.
        if sum(note.always_on for note in self.keyword_notes) > MAX_ALWAYS_ON_KEYWORD_NOTES:
            raise ValueError(f"at most {MAX_ALWAYS_ON_KEYWORD_NOTES} keyword notes can be always on")
        return self

    @model_validator(mode="after")
    def _check_situation_note_limits(self) -> Self:
        # 상한을 여기(요청 전용 모델)에 두는 이유는 `SituationNoteDraftItem` docstring. 길이는 키워드북처럼 보낸 글자
        # 그대로의 코드 포인트 수다.
        for setup in self.starting_setups:
            if len(setup.situation_notes) > MAX_SITUATION_NOTES_PER_SETUP:
                raise ValueError(f"a starting setup holds at most {MAX_SITUATION_NOTES_PER_SETUP} situation notes")
            for note in setup.situation_notes:
                if len(note.name) > SITUATION_NOTE_MAX_NAME_LENGTH:
                    raise ValueError(f"situation note name must be at most {SITUATION_NOTE_MAX_NAME_LENGTH} characters")
                if len(note.info_text) > SITUATION_NOTE_MAX_INFO_LENGTH:
                    raise ValueError(f"situation note text must be at most {SITUATION_NOTE_MAX_INFO_LENGTH} characters")
                if count_rules(note.condition_rules) > SITUATION_NOTE_MAX_RULES:
                    raise ValueError(f"a situation note holds at most {SITUATION_NOTE_MAX_RULES} condition rules")
        return self

    @model_validator(mode="after")
    def _check_stat_rule_limits(self) -> Self:
        # 상한을 여기(요청 전용 모델)에 두는 이유는 `StatRuleDraftItem` docstring. 폭 0 은 발동해도 아무 일도 하지 않는다.
        # 폭이 스탯 범위 폭을 넘는지는 여기서 보지 않고 발행이 막는다(`validate_story_publish`) — 작가가 범위를 좁히면
        # 이미 저장된 규칙이 넘게 되는데, 저장에서 막으면 그 초안의 자동저장이 편집마다 실패한다. 같은 스탯 안의 규칙 id
        # 중복은 막는다 — 저장이 id 로 행을 맞추므로 두 행이 같은 id 를 가지면 다음 저장에서 둘을 가를 수 없다.
        for setup in self.starting_setups:
            for stat in setup.stat_defs:
                if len(stat.rules) > MAX_STAT_RULES_PER_STAT:
                    raise ValueError(f"a stat holds at most {MAX_STAT_RULES_PER_STAT} rules")
                if _first_repeated([rule.id for rule in stat.rules]) is not None:
                    raise ValueError("stat rule ids must be unique within a stat")
                for rule in stat.rules:
                    if not 1 <= len(rule.condition) <= STAT_RULE_MAX_CONDITION_LENGTH:
                        raise ValueError(
                            f"stat rule condition must be 1-{STAT_RULE_MAX_CONDITION_LENGTH} characters after trimming"
                        )
                    if rule.delta == 0:
                        raise ValueError("stat rule delta must be a non-zero integer")
        return self


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
    default_user_name: str
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
