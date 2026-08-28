import { apiBaseUrl } from "@/shared/lib/api/client";

/** GET /auth/google는 풀페이지 리다이렉트 대상이라 axios가 아니라
 * window.location.href로 직접 이동한다(techspec-auth-onboarding.md §3). */
export function buildGoogleLoginUrl(redirectTo?: string): string {
  // `new URL("/auth/google", base)`는 절대경로라 base의 경로를 버린다 — base가
  // `https://host/api`처럼 경로를 가지면 `/api`가 사라진다. 문자열로 이어붙이되,
  // base의 트레일링 슬래시는 제거해야 `//auth/google`이 되지 않는다.
  const url = new URL(`${apiBaseUrl.replace(/\/+$/, "")}/auth/google`);
  if (redirectTo) url.searchParams.set("redirect", redirectTo);
  return url.toString();
}
