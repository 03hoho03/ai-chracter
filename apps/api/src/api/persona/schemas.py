import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import StringConstraints, field_validator

from api.core.schema import CamelModel

# persona-goal-prompt.md UP-5 — 한도의 권위는 BE다. FE zod의 20·500은 이 두 상수의 사본이다.
# `strip_whitespace`가 길이 검사보다 먼저 적용되므로 "공백만"은 trim 뒤 0자로 거부된다.
PERSONA_NAME_MAX_LENGTH = 20
PERSONA_DESCRIPTION_MAX_LENGTH = 500
# persona-goal-prompt.md UP-2 — `GET /me/personas`의 `maxCount`로 내려 보낸다(FE가 사본을 들지 않게).
PERSONA_MAX_COUNT = 10

PersonaName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=PERSONA_NAME_MAX_LENGTH)
]
PersonaDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=PERSONA_DESCRIPTION_MAX_LENGTH)
]
# persona-goal-prompt.md UP-4 — None이 "선택 안 함"이다(DB도 NULL).
PersonaGender = Literal["male", "female"] | None

# persona-goal-prompt.md UP-5 — 어드민 라벨 규칙 R-5(`admin/prompts.py`
# `_validate_prompt_draft_for_publish`)와 같은 집합에 `\r`을 더했다. 다음 런의 `{{user}}` 치환이
# 이름을 라벨·stop sequence 자리에 넣을 때를 위한 선제 방어다. 전각 `：`는 막지 않는다(stop
# sequence가 반각 `:`만 본다).
_FORBIDDEN_NAME_CHARACTERS = (":", "\n", "\r")


class PersonaUpsertRequest(CamelModel):
    """`PUT /me/personas/{id}`는 전체 교체라 필드에 기본값을 두지 않는다 — 빠진 필드가
    조용히 "선택 안 함"·빈 설명으로 덮어쓰이지 않게."""

    name: PersonaName
    gender: PersonaGender
    description: PersonaDescription

    @field_validator("name")
    @classmethod
    def _reject_forbidden_characters(cls, value: str) -> str:
        if any(character in value for character in _FORBIDDEN_NAME_CHARACTERS):
            raise ValueError("이름에는 콜론(:)이나 줄바꿈을 쓸 수 없어요.")
        return value


class PersonaCreateRequest(PersonaUpsertRequest):
    # persona-goal-prompt.md UP-23 — "기본이 없으면 켠다"는 규칙은 FE 체크박스 초기값 한 곳에만
    # 있다. BE는 받은 값만 따르므로 기본값 없는 필수 필드다(생략 → 422).
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
    필수다 — null(해제)은 명시해야 하고, 필드를 빼먹은 요청은 422다."""

    persona_id: uuid.UUID | None


class RoomPersonaResponse(CamelModel):
    persona_id: uuid.UUID | None
