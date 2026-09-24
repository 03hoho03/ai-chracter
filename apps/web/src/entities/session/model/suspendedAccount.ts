import { isApiError } from "@/shared/api/client";

/** 정지 계정 안내 — 로그인(`LoginForm`)·구글 온보딩(`SignUpWizard`)·비밀번호 변경(`ChangePasswordForm`)이
 * 같은 문장을 쓴다. features 슬라이스끼리는 import하지 못해(FSD) 여기로 내렸다 — 사본을 만들지 않는다
 * (backlog-sweep BS-10). */
export const SUSPENDED_ERROR_MESSAGE =
  "이용정지된 계정이에요. 문의사항은 ghwjd32123@gmail.com으로 연락해주세요.";

/** 정지 계정 403인가. 같은 403을 재동의 게이트(`{code: "LEGAL_RECONSENT_REQUIRED"}`)도 내므로 status만으로
 * 가르지 않고 detail까지 본다.
 *
 * 정지는 기다려서 풀리는 실패가 아니다 — 이 판정으로 고른 문구는 "잠시 후 다시 시도"라고 말하지 않는다
 * (backlog J-1). 인증 폼 배너의 다른 실패도 같은 규칙을 따르고, 각 status가 왜 기다려도 안 풀리는지는
 * 그 배너를 가진 feature가 적는다. */
export function isSuspendedError(error: unknown): boolean {
  return isApiError(error) && error.status === 403 && error.detail === "Account suspended";
}
