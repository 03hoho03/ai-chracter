import type { components } from "@ai-character-chat/api-types";

export type Persona = components["schemas"]["PersonaResponse"];
export type PersonaList = components["schemas"]["PersonaListResponse"];
export type PersonaGender = NonNullable<Persona["gender"]>;

/** BE `apps/api/src/api/persona/schemas.py`의
 * `PERSONA_NAME_MAX_LENGTH`·`PERSONA_DESCRIPTION_MAX_LENGTH`와 짝이 되는 사본이다(권위는 BE).
 * FE zod가 같은 한도를 먼저 막아 BE 422 원문이 사용자에게 가지 않게 한다. 개수 상한(10)은 사본을 두지
 * 않는다 — `GET /me/personas`의 `maxCount`를 쓴다. */
export const PERSONA_NAME_MAX_LENGTH = 20;
export const PERSONA_DESCRIPTION_MAX_LENGTH = 500;
