import type { Persona } from "@/entities/persona";

import type { PersonaFormValues } from "./schema";

/** 편집 폼의 초기값. 편집 폼에는 "기본으로 지정" 체크박스가 없으므로 `setAsDefault`는 쓰이지 않는다. */
export function serverToForm(persona: Persona): PersonaFormValues {
  return {
    name: persona.name,
    gender: persona.gender ?? "unspecified",
    description: persona.description,
    setAsDefault: false,
  };
}

/** 생성 폼의 초기값.
 *
 * persona-goal-prompt.md UP-23 — **기본 프로필이 없으면 "기본으로 지정"을 켠 채 시작한다. 이 규칙의 자리는
 * 여기 하나뿐이다**(BE는 받은 `setAsDefault`만 따른다). 켜진 체크박스를 보여 줘 "만들었더니 새 방에
 * 들어간다"를 사용자가 인지하게 한다(§6 R-18).
 *
 * UP-6·R-11 — 이름은 빈칸이다. 계정 닉네임으로 미리 채우지 않는다(처리방침상 닉네임은 LLM에 보내지 않는다). */
export function createFormDefaults(defaultPersonaId: string | null): PersonaFormValues {
  return {
    name: "",
    gender: "unspecified",
    description: "",
    setAsDefault: defaultPersonaId === null,
  };
}
