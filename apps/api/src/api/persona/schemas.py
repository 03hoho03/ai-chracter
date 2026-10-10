import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import StringConstraints, field_validator

from api.content.author_macros import user_name_error
from api.core.schema import CamelModel

# 한도의 권위는 BE다. FE zod의 20·500은 이 두 상수의 사본이다.
# `strip_whitespace`가 길이 검사보다 먼저 적용되므로 "공백만"은 trim 뒤 0자로 거부된다.
PERSONA_NAME_MAX_LENGTH = 20
PERSONA_DESCRIPTION_MAX_LENGTH = 500
# `GET /me/personas`의 `maxCount`로 내려 보낸다(FE가 사본을 들지 않게).
PERSONA_MAX_COUNT = 10

PersonaName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=PERSONA_NAME_MAX_LENGTH)
]
PersonaDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=PERSONA_DESCRIPTION_MAX_LENGTH)
]
# None이 "선택 안 함"이다(DB도 NULL).
PersonaGender = Literal["male", "female"] | None


class PersonaUpsertRequest(CamelModel):
    """`PUT /me/personas/{id}`는 전체 교체라 필드에 기본값을 두지 않는다 — 빠진 필드가
    조용히 "선택 안 함"·빈 설명으로 덮어쓰이지 않게."""

    name: PersonaName
    gender: PersonaGender
    description: PersonaDescription

    @field_validator("name")
    @classmethod
    def _reject_forbidden_characters(cls, value: str) -> str:
        # 이름은 작가 글의 `{{user}}` 자리에 들어간다. 무엇을 왜 막는지는 `user_name_error` 에 있다. 저장할 때만 막고
        # 이미 저장된 이름은 그대로 읽힌다(응답 모델에는 이 검사가 없다).
        error = user_name_error(value)
        if error is not None:
            raise ValueError(error)
        return value


class PersonaCreateRequest(PersonaUpsertRequest):
    # 첫 프로필은 이 값과 무관하게 기본이 된다(`create_persona`). 그 밖에는 받은 값만 따르므로 기본값 없는 필수
    # 필드다(생략 → 422).
    set_as_default: bool


class PersonaResponse(CamelModel):
    id: uuid.UUID
    name: str
    gender: PersonaGender
    description: str
    created_at: datetime
    updated_at: datetime


class PersonaListResponse(CamelModel):
    items: list[PersonaResponse]
    default_persona_id: uuid.UUID | None
    max_count: int


class PersonaSelectRequest(CamelModel):
    """`PUT /me/default-persona`와 `PUT /chat-rooms/{id}/persona`가 공유한다. `persona_id`는
    필수다 — null(해제)은 명시해야 하고, 필드를 빼먹은 요청은 422다. 기본 지정에서 null을 막는 건 그 라우트가 한다(방
    선택은 null이 "선택 안 함"이라 계속 받는다)."""

    persona_id: uuid.UUID | None


class RoomPersonaResponse(CamelModel):
    persona_id: uuid.UUID | None
    # 방 응답(`ChatRoomResponse.persona_name`)과 같은 값 — 화면이 방을 다시 읽지 않고 바꾼 이름을 바로 쓰게.
    # 기본값은 이 필드를 모르는 생성 타입·픽스처와의 호환용이다.
    persona_name: str | None = None
