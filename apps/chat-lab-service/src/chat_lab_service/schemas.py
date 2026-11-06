"""요청·응답 모델과 거부 이유.

칸 이름은 측정 서버 응답과 같은 camelCase 다. 웹은 묶음 목록의 `run` 칸을 측정 서버 스키마의 `RunListItem` 으로 읽으므로 여기서는
자유 객체로 둔다 — 서비스는 측정 서버 모델을 가져오지 않는다.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# 응답 본문의 `reason`. 401 은 하나로 묶고, 허용 밖·다른 신원·진짜 없음도 같은 404 하나로 묶는다 — 세부 이유는 접근 기록에만
# 남겨 응답만으로는 누가 허용되는지, 경로나 런이 있는지 알 수 없게 한다.
ServiceErrorReason = Literal[
    "unauthenticated",
    "notFound",
    "tooLarge",
    "notGzip",
    "notJsonObject",
    "noUploadHeader",
    "badUploadHeader",
    "provenanceFailed",
    "noContractVersion",
    "unsupportedContract",
    "legacyFormat",
    "badBundle",
    "runIdMismatch",
    "badDeleteBody",
    "keysUnavailable",
    "dbUnavailable",
    "internal",
]

# 접근 기록의 `reason` — 응답의 `reason` 보다 잘다.
AccessReason = Literal[
    "noToken",
    "malformedToken",
    "badAlgorithm",
    "unknownKey",
    "badSignature",
    "badAudience",
    "badIssuer",
    "expired",
    "notYetValid",
    "missingClaim",
    "keysUnavailable",
    "notAllowed",
    "wrongIdentity",
    "notFound",
    "tooLarge",
    "notGzip",
    "notJsonObject",
    "noUploadHeader",
    "badUploadHeader",
    "provenanceFailed",
    "noContractVersion",
    "unsupportedContract",
    "legacyFormat",
    "badBundle",
    "runIdMismatch",
    "badDeleteBody",
    "dbUnavailable",
    "internal",
]

RUN_ID_PATTERN = r"^[A-Za-z0-9_-]{1,1024}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
# git 커밋 id — SHA-1 저장소 40자, SHA-256 저장소 64자.
COMMIT_PATTERN = r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)


# 올리기 머리와 그 안의 칸은 측정 서버가 낸 camelCase 이름만, JSON 불·정수만 받는다 — 문자열로 온 "true"·"0" 을 바꿔 읽지 않는다.
_HEADER_PART = ConfigDict(strict=True, validate_by_name=False)


class ServiceError(BaseModel):
    detail: str
    reason: ServiceErrorReason


class Health(BaseModel):
    status: Literal["ok"]


class SourceCommit(CamelModel):
    """묶음을 만든 측정 서버 checkout 의 커밋."""

    model_config = _HEADER_PART

    commit: str = Field(pattern=COMMIT_PATTERN)
    dirty: bool


class Provenance(CamelModel):
    """이 런이 로컬 측정 서버에서 테스트 계정으로만 돈 것인지. 측정 서버가 낸 칸 가운데 이 일곱만 저장한다."""

    model_config = _HEADER_PART

    passed: bool
    base_local: bool | None
    room_found: bool
    owner_in_example_domain: bool
    outside_users: int
    exempted_users: int
    author_in_example_domain: bool | None

    def holds(self) -> bool:
        """`passed` 가 참이라고 적혀 있어도 칸들로 다시 계산한 판정이 함께 참이어야 받는다. 작가 칸은 경고라 넣지 않는다."""
        return (
            self.passed
            and self.base_local is not False
            and self.room_found
            and self.owner_in_example_domain
            and self.outside_users == 0
        )


class UploadHeader(CamelModel):
    """측정 서버 올리기 머리 응답 그대로. 모르는 칸은 버린다."""

    model_config = _HEADER_PART

    source_commit: SourceCommit
    provenance: Provenance


class Version(CamelModel):
    sha256: str
    version_number: int
    uploaded_at: datetime
    uploaded_by: str
    raw: bool
    contract_version: int
    source_commit: SourceCommit
    provenance: Provenance
    compressed_size: int
    uncompressed_size: int


class RunItem(CamelModel):
    run_id: str
    latest: Version
    # 지우지 않은 판 수.
    version_count: int
    run: dict[str, Any]


class RunList(BaseModel):
    items: list[RunItem]


class VersionList(CamelModel):
    run_id: str
    versions: list[Version]


class UploadResult(CamelModel):
    run_id: str
    sha256: str
    status: Literal["created", "exists", "restored"]
    version_number: int


class DeleteResult(CamelModel):
    run_id: str
    deleted_versions: int
