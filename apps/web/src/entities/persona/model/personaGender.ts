import type { PersonaGender } from "./persona";

/** persona-goal-prompt.md UP-4 — "선택 안 함"은 서버에서 `null`이라 이 맵에 없다(표시할 줄이 없다). */
export const PERSONA_GENDER_LABEL: Record<PersonaGender, string> = {
  male: "남성",
  female: "여성",
};
