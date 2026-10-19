from datetime import datetime
from typing import Literal

from pydantic import Field

from api.core.schema import CamelModel

# 공개 조회·어드민 편집·게시가 다루는 문서 종류. 값은 웹 경로와 같다(`/terms`,
# `/operation-policy` …) — Worker 의 canonical·사이트맵이 kind 를 그대로 경로로 쓴다.
LegalDocumentKind = Literal[
    "terms", "privacy", "operation-policy", "youth-policy", "refund-policy", "creator-payout-policy"
]

# 회원 동의를 기록하는 문서 종류. `users` 에 버전 컬럼이 있는 것은 이 둘뿐이고, 재동의
# 게이트·`GET /me`·가입 기록도 이 둘만 본다. 동의 요청이 문서 종류 전체를 받으면 동의
# 대상이 아닌 문서로 처리방침·국외이전 동의 버전을 덮어쓸 수 있으므로 따로 둔다.
LegalConsentKind = Literal["terms", "privacy"]

# 동의 단위. 가입 화면이 따로 받는 세 동의(약관, 개인정보 수집·이용, 국외이전)와 같다. 약관은 `terms` 하나, 처리방침은
# `collection`·`transfer` 둘이고 각각 `users.terms_version`·`privacy_version`·`transfer_version` 에 기록한다. 게시본의
# 재동의 범위도 이 값으로 적는다 — 처리방침을 고치면서 국외이전 동의만 다시 받는 판이 있을 수 있어서다.
LegalConsentUnit = Literal["terms", "collection", "transfer"]


class LegalUpcomingSummary(CamelModel):
    """현행판 응답에 곁들이는 시행 예정 판 요약. 전문은 `GET /legal/{kind}/upcoming` 이 준다."""

    version: str
    effective_at: datetime
    change_notice: str | None


class LegalDocumentPublicResponse(CamelModel):
    """`published_at` 은 게시(공지) 시각, `effective_at` 은 이 판이 현행이 된 시행 시각이다. `change_notice` 는 이 판의
    변경 안내(마크다운)이고 없으면 null 이다."""

    kind: LegalDocumentKind
    version: str
    body_markdown: str
    published_at: datetime
    effective_at: datetime
    change_notice: str | None
    upcoming: LegalUpcomingSummary | None


class LegalUpcomingDocumentResponse(CamelModel):
    kind: LegalDocumentKind
    version: str
    body_markdown: str
    published_at: datetime
    effective_at: datetime
    change_notice: str | None


class LegalChangeItem(CamelModel):
    """시행된 판 하나의 변경 안내. `reconsent_scopes` 는 그 판이 다시 받은 동의 단위다(없으면 빈 목록)."""

    version: str
    effective_at: datetime
    change_notice: str | None
    reconsent_scopes: list[LegalConsentUnit]


class LegalChangesResponse(CamelModel):
    """시행 순서로 최신 판이 먼저다."""

    items: list[LegalChangeItem]


class LegalConsentRequest(CamelModel):
    """동의할 단위를 `consents` 로 받는다. 버전은 받지 않는다 — 서버가 단위마다 그 문서의 현행판 버전을 기록한다."""

    consents: list[LegalConsentUnit] = Field(min_length=1)
