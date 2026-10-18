from datetime import datetime
from typing import Literal

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


class LegalUpcomingSummary(CamelModel):
    """현행판 응답에 곁들이는 시행 예정 판 요약. 전문은 `GET /legal/{kind}/upcoming` 이 준다."""

    version: str
    effective_at: datetime


class LegalDocumentPublicResponse(CamelModel):
    """`published_at` 은 게시(공지) 시각, `effective_at` 은 이 판이 현행이 된 시행 시각이다."""

    kind: LegalDocumentKind
    version: str
    body_markdown: str
    published_at: datetime
    effective_at: datetime
    upcoming: LegalUpcomingSummary | None


class LegalUpcomingDocumentResponse(CamelModel):
    kind: LegalDocumentKind
    version: str
    body_markdown: str
    published_at: datetime
    effective_at: datetime


class LegalConsentRequest(CamelModel):
    kind: LegalConsentKind
    version: str
