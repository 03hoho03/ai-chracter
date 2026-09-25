import { PERSONA_GENDER_LABEL, PERSONA_GENDERS } from "@/entities/persona";

/** 폼의 성별 선택지. 서버의 `null`(선택 안 함)을 토글 값으로 담으려고
 * `"unspecified"`를 둔다 — 서버 값과의 변환은 `formToServer`/`serverToForm`만 한다. 서버 멤버는
 * `PERSONA_GENDERS`에서 도출하므로 멤버가 늘면 아래 라벨 맵에서 컴파일이 깨진다. */
export const PERSONA_GENDER_OPTIONS = ["unspecified", ...PERSONA_GENDERS] as const;
export type PersonaGenderOption = (typeof PERSONA_GENDER_OPTIONS)[number];

export const PERSONA_GENDER_OPTION_LABEL: Record<PersonaGenderOption, string> = {
  unspecified: "선택 안 함",
  male: PERSONA_GENDER_LABEL.male,
  female: PERSONA_GENDER_LABEL.female,
};

/** Radix ToggleGroup은 선택된 항목을 다시 누르면 `""`를 emit한다 — 목록 밖 값은 `undefined`로 접는다. */
export function toPersonaGenderOption(value: string): PersonaGenderOption | undefined {
  return PERSONA_GENDER_OPTIONS.find((option) => option === value);
}
