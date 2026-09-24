import type { components } from "@ai-character-chat/api-types";

import type { PersonaFormValues } from "./schema";

type PersonaCreateRequest = components["schemas"]["PersonaCreateRequest"];
type PersonaUpsertRequest = components["schemas"]["PersonaUpsertRequest"];

function toServerGender(gender: PersonaFormValues["gender"]): PersonaUpsertRequest["gender"] {
  return gender === "unspecified" ? null : gender;
}

/** 폼값 → `PUT /me/personas/{id}`. 이 엔드포인트는 `setAsDefault`를 받지 않는다. */
export function formToUpdateRequest(values: PersonaFormValues): PersonaUpsertRequest {
  return { name: values.name, gender: toServerGender(values.gender), description: values.description };
}

/** 폼값 → `POST /me/personas`. `setAsDefault`는 BE에서 기본값 없는 필수 필드다(persona-goal-prompt.md UP-23). */
export function formToCreateRequest(values: PersonaFormValues): PersonaCreateRequest {
  return { ...formToUpdateRequest(values), setAsDefault: values.setAsDefault };
}
