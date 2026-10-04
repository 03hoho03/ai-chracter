import { defaultUserNameError } from "@/shared/lib/text/authorMacros";

import { PERSONA_NAME_MAX_LENGTH } from "./persona";

/**
 * 작품 기본 이름(빌더 칸)을 서버가 받지 않는 이유. 받으면 null.
 *
 * 작품 기본 이름은 대화 프로필 이름이 없을 때 같은 `{{user}}` 자리에 들어가므로 상한도 프로필 이름 상한을 쓴다. 서버처럼
 * 앞뒤 공백을 걷은 뒤 잰다. 상한은 UTF-16 길이로 재서 서버(코드 포인트)보다 엄격할 수는 있어도 느슨하지는 않다 — 폼이
 * 통과시킨 값을 서버가 거절하면 자동저장 전체가 멈춘다.
 */
export function defaultUserNameIssue(value: string): string | null {
  const name = value.trim();
  if (name.length > PERSONA_NAME_MAX_LENGTH) return `기본 이름은 ${PERSONA_NAME_MAX_LENGTH}자 이내로 입력해주세요`;
  return defaultUserNameError(name);
}
