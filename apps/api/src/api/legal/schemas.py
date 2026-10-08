from datetime import datetime
from typing import Literal

from api.core.schema import CamelModel

# 공개 조회·어드민 편집·게시가 다루는 문서 종류. 값은 웹 경로와 같다(`/terms`,
# `/operation-policy` …) — Worker 의 canonical·사이트맵이 kind 를 그대로 경로로 쓴다.
LegalDocumentKind = Literal["terms", "privacy", "operation-policy", "youth-policy", "refund-policy"]

# 회원 동의를 기록하는 문서 종류. `users` 에 버전 컬럼이 있는 것은 이 둘뿐이고, 재동의
# 게이트·`GET /me`·가입 기록도 이 둘만 본다. 동의 요청이 문서 종류 전체를 받으면 동의
# 대상이 아닌 문서로 처리방침·국외이전 동의 버전을 덮어쓸 수 있으므로 따로 둔다.
LegalConsentKind = Literal["terms", "privacy"]


class LegalDocumentPublicResponse(CamelModel):
    kind: LegalDocumentKind
    version: str
    body_markdown: str
    published_at: datetime


class LegalConsentRequest(CamelModel):
    kind: LegalConsentKind
    version: str
