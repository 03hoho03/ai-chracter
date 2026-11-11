import type { components } from "@ai-character-chat/api-types";

import type { FirstPersonaNameFormValues } from "./firstPersonaNameSchema";

type PersonaCreateRequest = components["schemas"]["PersonaCreateRequest"];

/** 폼값 → `POST /me/personas`. 이 모달은 이름만 받으므로 성별·설명은 비워 두고, 첫 프로필이라 곧바로 기본으로 만든다.
 * 스키마는 공백을 걷은 값으로 검사만 하고 값은 그대로 두므로 앞뒤 공백은 여기서 걷는다. */
export function formToServer(values: FirstPersonaNameFormValues): PersonaCreateRequest {
  return { name: values.name.trim(), gender: null, description: "", setAsDefault: true };
}
