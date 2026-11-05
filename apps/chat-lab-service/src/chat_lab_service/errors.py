"""거부 응답 하나의 모양과, 기록 이유에서 응답 이유로 가는 표."""

from starlette.responses import JSONResponse

from chat_lab_service.schemas import AccessReason, ServiceError, ServiceErrorReason

# 401·404 는 이유가 무엇이든 본문 바이트가 하나다 — 본문으로 허용 여부나 경로·런의 존재를 가를 수 없게.
UNAUTHENTICATED_DETAIL = "Access 로그인이 필요하다"
NOT_FOUND_DETAIL = "찾을 수 없다"

_RESPONSE_REASON: dict[AccessReason, ServiceErrorReason] = {
    "noToken": "unauthenticated",
    "malformedToken": "unauthenticated",
    "badAlgorithm": "unauthenticated",
    "unknownKey": "unauthenticated",
    "badSignature": "unauthenticated",
    "badAudience": "unauthenticated",
    "badIssuer": "unauthenticated",
    "expired": "unauthenticated",
    "notYetValid": "unauthenticated",
    "missingClaim": "unauthenticated",
    "notAllowed": "notFound",
    "wrongIdentity": "notFound",
    "notFound": "notFound",
    "keysUnavailable": "keysUnavailable",
    "tooLarge": "tooLarge",
    "notGzip": "notGzip",
    "notJsonObject": "notJsonObject",
    "noUploadHeader": "noUploadHeader",
    "badUploadHeader": "badUploadHeader",
    "provenanceFailed": "provenanceFailed",
    "noContractVersion": "noContractVersion",
    "unsupportedContract": "unsupportedContract",
    "legacyFormat": "legacyFormat",
    "badBundle": "badBundle",
    "runIdMismatch": "runIdMismatch",
    "badDeleteBody": "badDeleteBody",
    "dbUnavailable": "dbUnavailable",
    "internal": "internal",
}


class ServiceHTTPError(Exception):
    """처리기가 응답으로 바꾸고 기록에 `reason` 을 남기는 거부."""

    def __init__(self, status: int, reason: AccessReason, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.reason = reason
        self.detail = detail


def not_found() -> ServiceHTTPError:
    return ServiceHTTPError(404, "notFound", NOT_FOUND_DETAIL)


def error_response(status: int, reason: AccessReason, detail: str) -> JSONResponse:
    response_reason = _RESPONSE_REASON[reason]
    if response_reason == "unauthenticated":
        detail = UNAUTHENTICATED_DETAIL
    elif response_reason == "notFound":
        detail = NOT_FOUND_DETAIL
    return JSONResponse(ServiceError(detail=detail, reason=response_reason).model_dump(mode="json"), status_code=status)
