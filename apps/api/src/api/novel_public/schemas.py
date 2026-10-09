import uuid
from datetime import datetime

from api.core.schema import CamelModel
from api.db.models.novel import (
    NovelPublicationModerationStatus,
    NovelPublicationVisibility,
    NovelScreeningOutcome,
    NovelScreeningPart,
)
from api.novel_public.access import NewPublishBlock, RepublishBlock


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
