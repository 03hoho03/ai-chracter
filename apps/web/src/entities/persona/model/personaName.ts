import { userNameError } from "@/shared/lib/text/authorMacros";

import { PERSONA_NAME_MAX_LENGTH } from "./persona";

/**
 * 대화 프로필 이름을 서버가 받지 않는 이유. 받으면 null. 서버(`PersonaName`)처럼 앞뒤 공백을 걷은 뒤 잰다 — 비면 안 되고,
 * 상한 안이어야 하며, 작가 글의 `{{user}}` 자리에 들어갈 수 있어야 한다. 프로필 관리 폼 밖에서 이름만 받는 화면(가입·첫
 * 대화)이 같은 규칙을 쓰려고 여기 둔다. 상한은 UTF-16 길이라 서버(코드 포인트)보다 엄격할 수는 있어도 느슨하지는 않다.
 */
export function personaNameIssue(value: string): string | null {
  const name = value.trim();
  if (name === "") return "이름을 입력해주세요";
  if (name.length > PERSONA_NAME_MAX_LENGTH) return `이름은 ${PERSONA_NAME_MAX_LENGTH}자 이내로 입력해주세요`;
  return userNameError(name);
}
