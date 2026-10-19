import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from api.core.schema import CamelModel
from api.db.models.moderation import ReportReasonCategory, ReportStatus
from api.db.models.novel import (
    NovelContentType,
    NovelPublicationModerationStatus,
    NovelPublicationReviewStatus,
    NovelPublicationVisibility,
    NovelScreeningOutcome,
    NovelScreeningPart,
    NOVEL_CHANGE_SUMMARY_MAX_LENGTH,
)
from api.novel_public.access import NewPublishBlock, RepublishBlock
from api.novelize.schemas import CHAPTER_BODY_MAX_LENGTH


class NovelPublishRequest(CamelModel):
    """공개 요청 하나 = 화 하나(또는 소설 제목·소개만). `chapter_id` 가 다음 화(공개한 화 수 + 1번째)면 그 화를 새로
    공개하고, 이미 공개한 화면 바뀐 경우 다시 공개한다. 비우면 소설 제목·소개만 다시 공개한다(처음 공개에는 1화가 있어야
    한다). 어느 경우든 소설 제목·소개가 공개본과 다르면 같은 요청에서 함께 심사해 다시 공개하고, 거둔 공개는 다시 연다.

    여러 화를 한 요청에 받지 않는 것은 심사 호출이 화마다 수 초 걸려 요청 하나가 그만큼 붙잡히기 때문이다 — 화면이 1화부터
    한 화씩 부르면 앞 화까지는 공개된 채로 남고 이어짐도 요청마다 지켜진다.

    `free` 는 새로 공개하는 화의 가격 선택이다(정책 스위치가 켜졌을 때만 본다). 참이면 무료, 거짓이면 유료(화당 가격)이고,
    비우면 앞 화(`NOVEL_FREE_CHAPTER_COUNT` 까지)와 무료로 나간 적 있는 번호(상태 응답의 `free_locked_ordinals`)는 무료·그
    밖은 유료다. 앞 화와 무료로 나간 적 있는 번호는 유료로 낼 수 없다(409 `NOVEL_CHAPTER_PRICE_LOCKED`). 이미 공개한 화를
    다시 낼 때 비우면 지금 가격을 그대로 두고 — 이 칸을 모르는 옛 화면도 무료로 공개한 화를 고쳐 다시 낼 수 있게 — 무료로
    공개한 화에 거짓을 보내면 409 `NOVEL_CHAPTER_PRICE_LOCKED`(무료로 공개한 화는 다시 유료가 되지 않는다), 유료 화에 참을
    보내면 409 `NOVEL_CHAPTER_ALREADY_PRICED`(무료로 바꾸기는 따로 있는 "무료로 전환"만 한다 — 다시 공개 흐름을 타면 심사·판
    올림이 따라온다). 스위치가 꺼져 있으면 이 칸을 보지 않고 새 화는 앞 화 무료·그 뒤 유료로 저장한다(지금 약관의 규칙).

    `change_summary` 는 이미 공개한 화를 고쳐 다시 낼 때 작가가 쓰는 짧은 변경 요약이다(앞뒤 공백을 덜고 1~100자, 빈 글·
    공백만이면 보내지 않은 것과 같다 — 입력 칸을 비운 채 보내는 화면이 요약이 필요 없는 요청에서 422 를 받지 않게). 정책
    스위치가 켜져 있으면 그런 요청에 꼭 있어야 하고(없으면 422 `NOVEL_CHANGE_SUMMARY_REQUIRED`), 공개 화면 글이라 고친 화의
    글과 함께 심사한 뒤 새 판에 남는다 — 산 사람의 판 고르기가 공개 시각과 함께 보인다. 새 화(첫 판)·소설 제목·소개만 다시
    내는 요청·스위치가 꺼진 동안에는 보지 않는다."""

    chapter_id: uuid.UUID | None = None
    free: bool | None = None
    change_summary: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOVEL_CHANGE_SUMMARY_MAX_LENGTH)]
        | None
    ) = None

    @field_validator("change_summary", mode="before")
    @classmethod
    def _blank_summary_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class NovelPublicationScreening(CamelModel):
    """가장 최근 텍스트 심사의 판정. 게시자에게는 어느 화의 어느 글이 걸렸는지만 보이고 심사 모델이 쓴 사유는 싣지 않는다."""

    outcome: NovelScreeningOutcome
    chapter_ordinal: int | None
    flagged_parts: list[NovelScreeningPart]
    created_at: datetime


class NovelPublishedChapter(CamelModel):
    """공개한 화 하나와 지금 가격(0 = 무료). 앞 화는 늘 0 이다."""

    chapter_id: uuid.UUID
    ordinal: int
    price: int


class NovelPublicationStatusResponse(CamelModel):
    """게시자가 보는 공개 상태. 화면이 이 값들로 "공개 전·공개 중·확인 실패·원작 허락 미달·원작 비공개·허락 하향 뒤·운영
    조치" 상태를 가른다("확인 중"과 심사 장애는 요청 중·요청 실패로 화면이 안다).

    - `published`: 공개 상태 행이 있는가(한 번이라도 공개했는가). 거둔 뒤에도 참이다.
    - `visibility`·`moderation_status`: 공개 범위·이용제한 두 축. 공개한 적이 없으면 비어 있다.
    - `published_chapter_count`: 1화부터 이어진 공개 화 수. `chapter_count` 는 소설의 화 수다.
    - `published_chapters`: 공개한 화마다 가격(번호 순). 화면이 무료로 공개한 화를 고정으로 그리고 유료 화에 "무료로 전환"을
      건다.
    - `free_locked_ordinals`: 아직 공개하지 않은 번호 중 무료로만 공개할 수 있는 번호(오름차순) — 무료로 공개하거나 무료로
      전환한 화를 지우고 다시 만든 번호다. 화면이 그 번호의 가격 선택을 "무료 고정"으로 그린다. 정책 스위치가 꺼져 있으면
      비어 있다.
    - `changed_chapter_ordinals`·`metadata_changed`: 공개한 뒤 고쳐서 공개본과 다른 화·소설 제목·소개. 다시 공개해야
      반영된다.
    - `new_publish_block`: 새로 공개(처음 공개·다음 화)할 수 없는 이유. 없으면 비어 있다.
    - `republish_block`: 이미 공개한 것을 다시 내거나 거둔 공개를 다시 열 수 없는 이유.
    - `screening_rejections_left`: 오늘 더 걸릴 수 있는 심사 횟수(상한 `screening_rejection_limit`). 상한을 적용하지 않는
      계정이면 비어 있다.
    - `review_status`: 첫 공개의 운영자 심사 — 대기·승인·반려. 심사 없이 공개됐거나 공개한 적이 없으면 비어 있다. 대기·
      반려인 동안 `visibility` 는 `withdrawn` 이지만 게시자가 거둔 것이 아니다.
    - `review_reason`: 반려 사유. 운영자가 쓴 글 그대로이고 반려일 때만 있다. `reviewed_at` 은 마지막 승인·반려 시각이다.
    - `review_required`: 지금 공개하면 독자에게 바로 열리지 않고 운영자 승인을 기다리는가(정책 스위치가 켜졌고 아직 독자에게
      보인 적 없는 소설).
    - `sales_stopped`: 운영자가 이 공개 소설의 판매를 멈췄는가. 멈춘 동안 목록에 보이지 않고 새로 팔리지 않으며(산 사람은
      계속 읽는다) 새 화·다시 공개를 낼 수 없다. 이용제한(`moderation_status`)과 따로 걸리고 풀린다."""

    published: bool
    visibility: NovelPublicationVisibility | None
    moderation_status: NovelPublicationModerationStatus | None
    published_chapter_count: int
    published_chapters: list[NovelPublishedChapter]
    free_locked_ordinals: list[int]
    chapter_count: int
    changed_chapter_ordinals: list[int]
    metadata_changed: bool
    new_publish_block: NewPublishBlock | None
    republish_block: RepublishBlock | None
    last_screening: NovelPublicationScreening | None
    screening_rejections_left: int | None
    screening_rejection_limit: int
    first_published_at: datetime | None
    published_at: datetime | None
    review_status: NovelPublicationReviewStatus | None
    review_reason: str | None
    reviewed_at: datetime | None
    review_required: bool
    sales_stopped: bool


# ── 독자 화면 ───────────────────────────────────────────────────────────────
# 독자 화면은 공개 시점에 얼려 심사를 거친 글(공개본 사본)과 원작 썸네일만 싣는다. 화 요약·인물 카드·소설 생성 표지는
# 얼리지도 심사하지도 않은 소유자 글이라 이 응답들에 칸이 없다.

PublicNovelListSort = Literal["latest", "popular"]

# 독자에게 화 하나가 어떤 상태인가. `free`: 앞 화라 누구나 무료. `owned`: 소장함. `locked`: 소장해야 읽는다.
# `publisher`: 게시자 본인이라 언제나 무료로 읽는다(가격 표식을 그리지 않는다).
PublicNovelChapterAccess = Literal["free", "owned", "locked", "publisher"]

# 소장한 사람이 더 볼 수 없게 된 이유(410 `NOVEL_READING_ENDED` 의 `reason`). `deleted`: 게시자가 화·소설을 지워 환급함.
# `publisher_withdrawn`: 게시자가 탈퇴함. `withdrawn`: 게시자가 공개를 거둠. `restricted`: 운영 조치(게시자 정지 포함 —
# 정지 사실은 따로 드러내지 않는다). `source_unavailable`: 원작이 이용제한·삭제됨. `service_off`: 노벨을 꺼 둠.
PublicNovelEndedReason = Literal[
    "deleted", "publisher_withdrawn", "withdrawn", "restricted", "source_unavailable", "service_off"
]


class PublicNovelSource(CamelModel):
    """원작 표기. `title`·`character_name` 은 소설을 만들 때의 원작 사본이다. `cover_url` 은 원작의 지금 게시본 썸네일 —
    노벨 표지는 이것뿐이고, 원작자가 탈퇴했거나 썸네일이 없으면 비어 있다(화면이 기본 표지를 그린다). `linkable` 은 원작이
    지금 작품 목록에 실려 원작 상세로 링크를 걸 수 있는가다. `creator_nickname` 은 원작자의 지금 닉네임이다(복사해 두지 않고
    읽을 때 가져온다) — 원작자가 탈퇴했거나 원작 행이 없으면 비어 있다. `unofficial` 은 원작자가 게시자가 아닌가(화면이
    "비공식 2차 창작"을 붙인다)이고, 원작 행이 없으면 참이다(근거 없이 공식으로 표시하지 않는다). `creator_withdrawn` 은
    원작자가 탈퇴했는가다 — 이름이 빈 것은 탈퇴·원작 행 없음·닉네임 미설정이 모두 같아 보여, 화면이 "탈퇴한 사용자"로 그릴지를
    이것으로 가른다(원작 행이 없으면 거짓)."""

    content_id: uuid.UUID
    content_type: NovelContentType
    title: str
    character_name: str | None
    cover_url: str | None
    linkable: bool
    creator_nickname: str | None
    unofficial: bool
    creator_withdrawn: bool


class PublicNovelListItem(CamelModel):
    """노벨 목록의 한 줄. `title` 은 공개본 제목(비어 있던 공개본은 원작 제목), `synopsis` 는 공개본 소개다.
    `published_at` 은 공개 화면 글이 마지막으로 바뀐 시각(최신순 정렬 키)이다. `publisher_withdrawn` 은 게시자가 탈퇴했는가다
    (탈퇴한 게시자의 소설은 판매를 멈춘 채 소장자에게만 보인다) — 닉네임이 비어 있는 살아 있는 게시자와 가른다."""

    id: uuid.UUID
    title: str
    synopsis: str
    source: PublicNovelSource
    publisher_nickname: str | None
    publisher_withdrawn: bool
    chapter_count: int
    like_count: int
    view_count: int
    published_at: datetime


class PublicNovelListResponse(CamelModel):
    items: list[PublicNovelListItem]
    next_cursor: str | None


class PublicNovelOwnedItem(PublicNovelListItem):
    """소장 목록의 한 줄 — 노벨 목록의 한 줄에 판매 중지 표시를 더한 것. `sales_stopped` 는 노벨 목록에서 빠졌지만 소장자
    조건으로 열리는 노벨인가다(작품 정보의 같은 이름 값과 같다)."""

    sales_stopped: bool


class PublicNovelOwnedListResponse(CamelModel):
    items: list[PublicNovelOwnedItem]
    next_cursor: str | None


class PublicNovelReadingPosition(CamelModel):
    """화 하나를 읽던 자리. `edition` 은 그때 읽던 공개본 판이다 — 지금 판과 다르면 문단 수가 달라졌을 수 있어 화면이
    `paragraph_count` 비율로 옮긴다. `finished` 는 그 화를 끝까지 읽은 적이 있는가다."""

    paragraph_index: int
    paragraph_count: int
    edition: int
    finished: bool


class PublicNovelChapterItem(CamelModel):
    """목차의 화 한 줄. `title` 은 공개본 화 제목(비어 있으면 화면이 "n화"로 그린다). `price` 는 그 화의 가격이고 무료 화면
    비어 있다 — 앞 화와 작가가 무료로 공개하거나 무료로 바꾼 화(소장·게시자 본인이어도 가격은 싣고, 표식은 `access` 로
    고른다). 산 뒤 무료가 된 화는 산 사람에게도 `free` 다."""

    id: uuid.UUID
    ordinal: int
    title: str | None
    access: PublicNovelChapterAccess
    price: int | None
    reading_position: PublicNovelReadingPosition | None


class PublicNovelLastRead(CamelModel):
    """이 소설에서 가장 최근에 읽은 자리("이어 읽기"). 그 화가 지금 공개 화일 때만 싣는다."""

    chapter_id: uuid.UUID
    ordinal: int
    paragraph_index: int
    paragraph_count: int
    edition: int
    updated_at: datetime


class PublicNovelDetailResponse(CamelModel):
    """노벨 작품 정보. 제목·소개·화 제목은 공개본 사본이다.

    - `is_publisher`: 보는 사람이 게시자 본인인가(모든 화를 무료로 읽고, 화면이 "내 소설에서 관리"를 보인다).
    - `free_chapter_count`·`chapter_price`: 앞 무료 화 수와 유료 화의 화당 가격(지금 설정값 — 이미 공개한 유료 화도 이
      값이다). 6화 이후에도 작가가 무료로 둔 화가 있을 수 있으므로 화마다의 값은 목차의 `price` 다.
    - `liked`: 보는 사람이 좋아요했는가.
    - `sales_stopped`: 새로 보이거나 팔리지 않는 노벨을 소장자가 열었다(게시자의 거둠·정지·탈퇴, 원작자 정지로 인한 원작
      일괄 제한, 판매된 소설 삭제). 산 화·무료 화·목차는 그대로 읽고, 사지 않은 유료 화는 잠김으로 보이되 살 수 없다.
    - `publisher_withdrawn`: 게시자가 탈퇴했다. 그때 `publisher_user_id`·`publisher_nickname` 은 비어 있다 — 탈퇴한 사람의
      회원 id 를 남겨 두면 이 소설을 그 사람과 다시 이어 붙일 수 있다."""

    id: uuid.UUID
    title: str
    synopsis: str
    source: PublicNovelSource
    publisher_user_id: uuid.UUID | None
    publisher_nickname: str | None
    publisher_withdrawn: bool
    is_publisher: bool
    chapters: list[PublicNovelChapterItem]
    free_chapter_count: int
    chapter_price: int
    like_count: int
    liked: bool
    view_count: int
    last_read: PublicNovelLastRead | None
    first_published_at: datetime
    published_at: datetime
    sales_stopped: bool = False


class PublicNovelChapterLink(CamelModel):
    """화 읽기 화면의 이전·다음 화. 다음 화가 잠겼으면 화면이 버튼에 가격을 미리 붙인다."""

    id: uuid.UUID
    ordinal: int
    access: PublicNovelChapterAccess


class PublicNovelEdition(CamelModel):
    """산 사람의 판 고르기에 보이는 판 하나 — 판 번호, 그 판을 공개한 시각, 작가가 그 판을 낼 때 쓴 변경 요약. 첫 판·정책
    스위치가 꺼진 동안 낸 판·요약을 받기 전의 판은 요약이 비어 있다."""

    edition: int
    published_at: datetime
    change_summary: str | None


class PublicNovelChapterResponse(CamelModel):
    """노벨 화 하나. `access` 가 `locked` 면 본문(`paragraphs`)과 작가의 말이 비어 있고 `price` 로 소장 화면을 그린다 —
    잠긴 화의 글은 한 글자도 싣지 않는다. 읽을 수 있으면 공개본 개정의 본문을 문단 배열로 싣는다(소유자 화 조회의
    `paragraphs` 와 같은 나눔이라 읽은 자리의 문단 번호가 같은 뜻이다). `edition` 은 실어 준 글의 판이다(읽은 자리 저장에
    싣는다) — 보통은 지금 판이고, 산 사람이 산 때의 판을 고르면 그 판이다.

    `purchased_edition` 은 그 화를 산 사람에게만, 산 때의 판이 지금 판과 다를 때 싣는다(정책 스위치가 켜졌을 때). 판 이력이
    생기기 전의 판을 샀으면 남아 있는 가장 오래된 판으로 대신한다. 그 판 번호를 쿼리 `edition` 으로 보내면 그 판의 본문·
    제목·작가의 말을 준다. `latest_edition` 은 그때 함께 싣는 지금 판(최신 판)이다 — 판 고르기는 이 두 판만 보이고, 사이에
    낸 판은 싣지 않는다. 둘 다 산 때의 판을 골라 읽는 중에도 실린다. `sales_stopped` 는 작품 정보의 같은 칸과 같다."""

    novel_id: uuid.UUID
    novel_title: str
    id: uuid.UUID
    ordinal: int
    title: str | None
    access: PublicNovelChapterAccess
    price: int | None
    edition: int
    paragraphs: list[str] | None
    author_note: str | None
    previous_chapter: PublicNovelChapterLink | None
    next_chapter: PublicNovelChapterLink | None
    reading_position: PublicNovelReadingPosition | None
    purchased_edition: PublicNovelEdition | None = None
    latest_edition: PublicNovelEdition | None = None
    sales_stopped: bool = False


class PublicNovelReadingPositionRequest(CamelModel):
    """노벨 화를 읽던 자리. 소유자 읽은 자리와 같은 꼴이고 개정 id 대신 공개본 판(`edition`)을 싣는다. 같은 값을 다시
    보내도 결과가 같고, `finished` 가 한 번 참이 되면 그 화는 앞부분을 다시 읽어 저장해도 다 읽은 화로 남는다."""

    # 상한은 소유자 읽은 자리와 같은 이유다 — 문단 수는 본문 글자 수를 넘지 못하고, 상한이 없으면 큰 값이 DB 정수 칸을
    # 넘쳐 500 이 된다.
    paragraph_index: int = Field(ge=0, lt=CHAPTER_BODY_MAX_LENGTH)
    paragraph_count: int = Field(ge=1, le=CHAPTER_BODY_MAX_LENGTH)
    # 판 번호 상한은 DB 정수 칸의 최댓값이다(넘치면 500).
    edition: int = Field(ge=1, le=2_147_483_647)
    finished: bool


class PublicNovelHomeItem(CamelModel):
    """홈 노벨 섹션의 한 칸. 지표는 싣지 않는다(홈은 그림·제목·원작만 그린다)."""

    id: uuid.UUID
    title: str
    source: PublicNovelSource


class PublicNovelHomeResponse(CamelModel):
    """운영자가 고른 노벨 가운데 지금 읽을 수 있는 것, 자리 순. 비어 있으면 홈은 섹션을 그리지 않는다 — 고른 노벨이 없을 때
    인기순으로 채우지 않는다."""

    items: list[PublicNovelHomeItem]


class PublicNovelCommentCreateRequest(CamelModel):
    """화 댓글 본문. 빈 글·1,000자(화면에 보이는 글자 수) 초과는 라우트가 422 로 거른다."""

    body: str


class PublicNovelCommentItem(CamelModel):
    """화 댓글 하나와 보는 사람이 그 댓글에 할 수 있는 일. `is_publisher` 는 작성자가 이 노벨의 게시자인가(화면의 "게시자"
    표식)이고, `can_delete` 는 작성자 본인이거나 보는 사람이 게시자일 때, `can_report` 는 남의 댓글일 때 참이다."""

    id: uuid.UUID
    author_nickname: str | None
    is_publisher: bool
    is_mine: bool
    can_delete: bool
    can_report: bool
    body: str
    created_at: datetime


class PublicNovelCommentListResponse(CamelModel):
    """최신순 한 페이지. `total_count` 는 그 화에 보이는 댓글 수다(지운 댓글·운영자가 숨긴 댓글은 빠진다)."""

    items: list[PublicNovelCommentItem]
    next_cursor: str | None
    total_count: int


class PublicNovelReportRequest(CamelModel):
    """노벨 신고. `chapter_id` 를 주면 그 공개 화를, 비우면 소설 전체를 신고한다."""

    reason_category: ReportReasonCategory
    chapter_id: uuid.UUID | None = None


class PublicNovelCommentReportRequest(CamelModel):
    reason_category: ReportReasonCategory


class PublicNovelReportResponse(CamelModel):
    """같은 대상을 다시 신고하면 처음 신고를 그대로 돌려준다(사유·증거를 바꾸지 않는다)."""

    report_id: uuid.UUID
    status: ReportStatus
