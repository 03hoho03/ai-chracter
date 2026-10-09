import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.novel import (
    NovelContentType,
    NovelPublicationModerationStatus,
    NovelPublicationVisibility,
    NovelScreeningOutcome,
    NovelScreeningPart,
)
from api.novel_public.access import NewPublishBlock, RepublishBlock
from api.novelize.schemas import CHAPTER_BODY_MAX_LENGTH


class NovelPublishRequest(CamelModel):
    """공개 요청 하나 = 화 하나(또는 소설 제목·소개만). `chapter_id` 가 다음 화(공개한 화 수 + 1번째)면 그 화를 새로
    공개하고, 이미 공개한 화면 바뀐 경우 다시 공개한다. 비우면 소설 제목·소개만 다시 공개한다(처음 공개에는 1화가 있어야
    한다). 어느 경우든 소설 제목·소개가 공개본과 다르면 같은 요청에서 함께 심사해 다시 공개하고, 거둔 공개는 다시 연다.

    여러 화를 한 요청에 받지 않는 것은 심사 호출이 화마다 수 초 걸려 요청 하나가 그만큼 붙잡히기 때문이다 — 화면이 1화부터
    한 화씩 부르면 앞 화까지는 공개된 채로 남고 이어짐도 요청마다 지켜진다."""

    chapter_id: uuid.UUID | None = None


class NovelPublicationScreening(CamelModel):
    """가장 최근 텍스트 심사의 판정. 게시자에게는 어느 화의 어느 글이 걸렸는지만 보이고 심사 모델이 쓴 사유는 싣지 않는다."""

    outcome: NovelScreeningOutcome
    chapter_ordinal: int | None
    flagged_parts: list[NovelScreeningPart]
    created_at: datetime


class NovelPublicationStatusResponse(CamelModel):
    """게시자가 보는 공개 상태. 화면이 이 값들로 "공개 전·공개 중·확인 실패·원작 허락 미달·원작 비공개·허락 하향 뒤·운영
    조치" 상태를 가른다("확인 중"과 심사 장애는 요청 중·요청 실패로 화면이 안다).

    - `published`: 공개 상태 행이 있는가(한 번이라도 공개했는가). 거둔 뒤에도 참이다.
    - `visibility`·`moderation_status`: 공개 범위·이용제한 두 축. 공개한 적이 없으면 비어 있다.
    - `published_chapter_count`: 1화부터 이어진 공개 화 수. `chapter_count` 는 소설의 화 수다.
    - `changed_chapter_ordinals`·`metadata_changed`: 공개한 뒤 고쳐서 공개본과 다른 화·소설 제목·소개. 다시 공개해야
      반영된다.
    - `new_publish_block`: 새로 공개(처음 공개·다음 화)할 수 없는 이유. 없으면 비어 있다.
    - `republish_block`: 이미 공개한 것을 다시 내거나 거둔 공개를 다시 열 수 없는 이유.
    - `screening_rejections_left`: 오늘 더 걸릴 수 있는 심사 횟수(상한 `screening_rejection_limit`). 상한을 적용하지 않는
      계정이면 비어 있다."""

    published: bool
    visibility: NovelPublicationVisibility | None
    moderation_status: NovelPublicationModerationStatus | None
    published_chapter_count: int
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
    지금 작품 목록에 실려 원작 상세로 링크를 걸 수 있는가다."""

    content_id: uuid.UUID
    content_type: NovelContentType
    title: str
    character_name: str | None
    cover_url: str | None
    linkable: bool


class PublicNovelListItem(CamelModel):
    """노벨 목록의 한 줄. `title` 은 공개본 제목(비어 있던 공개본은 원작 제목), `synopsis` 는 공개본 소개다.
    `published_at` 은 공개 화면 글이 마지막으로 바뀐 시각(최신순 정렬 키)이다."""

    id: uuid.UUID
    title: str
    synopsis: str
    source: PublicNovelSource
    publisher_nickname: str | None
    chapter_count: int
    like_count: int
    view_count: int
    published_at: datetime


class PublicNovelListResponse(CamelModel):
    items: list[PublicNovelListItem]
    next_cursor: str | None


class PublicNovelReadingPosition(CamelModel):
    """화 하나를 읽던 자리. `edition` 은 그때 읽던 공개본 판이다 — 지금 판과 다르면 문단 수가 달라졌을 수 있어 화면이
    `paragraph_count` 비율로 옮긴다. `finished` 는 그 화를 끝까지 읽은 적이 있는가다."""

    paragraph_index: int
    paragraph_count: int
    edition: int
    finished: bool


class PublicNovelChapterItem(CamelModel):
    """목차의 화 한 줄. `title` 은 공개본 화 제목(비어 있으면 화면이 "n화"로 그린다). `price` 는 앞 무료 화가 아니면 지금
    화당 가격이고 무료 화면 비어 있다(소장·게시자 본인이어도 가격은 싣고, 표식은 `access` 로 고른다)."""

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
    - `free_chapter_count`·`chapter_price`: "1~5화 무료 · 6화부터 화당 30클로버" 안내용 지금 설정값.
    - `liked`: 보는 사람이 좋아요했는가."""

    id: uuid.UUID
    title: str
    synopsis: str
    source: PublicNovelSource
    publisher_user_id: uuid.UUID
    publisher_nickname: str | None
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


class PublicNovelChapterLink(CamelModel):
    """화 읽기 화면의 이전·다음 화. 다음 화가 잠겼으면 화면이 버튼에 가격을 미리 붙인다."""

    id: uuid.UUID
    ordinal: int
    access: PublicNovelChapterAccess


class PublicNovelChapterResponse(CamelModel):
    """노벨 화 하나. `access` 가 `locked` 면 본문(`paragraphs`)과 작가의 말이 비어 있고 `price` 로 소장 화면을 그린다 —
    잠긴 화의 글은 한 글자도 싣지 않는다. 읽을 수 있으면 공개본 개정의 본문을 문단 배열로 싣는다(소유자 화 조회의
    `paragraphs` 와 같은 나눔이라 읽은 자리의 문단 번호가 같은 뜻이다). `edition` 은 공개본 판이다(읽은 자리 저장에 싣는다)."""

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
