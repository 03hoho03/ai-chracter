import { isApiError } from "@/shared/api/client";

/** 세션이 서버에서 사라졌다는 401인가(로그아웃한 다른 탭, 정지로 인한 세션 폐기, 만료).
 * 같은 401을 로그인 실패(`"Invalid email or password"`)도 내므로 status만으로 가르지 않고 detail까지
 * 본다 — 로그인 폼의 실패가 세션을 건드리면 안 된다. */
export function isSessionLostError(error: unknown): boolean {
  return isApiError(error) && error.status === 401 && error.detail === "Not authenticated";
}
