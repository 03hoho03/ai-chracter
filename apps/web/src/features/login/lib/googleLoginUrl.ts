import { apiClient } from "../../../shared/lib/api/client";

/** GET /auth/google는 풀페이지 리다이렉트 대상이라 axios가 아니라
 * window.location.href로 직접 이동한다(techspec-auth-onboarding.md §3). */
export function buildGoogleLoginUrl(redirectTo?: string): string {
  const baseURL = apiClient.defaults.baseURL;
  const url = new URL("/auth/google", baseURL);
  if (redirectTo) url.searchParams.set("redirect", redirectTo);
  return url.toString();
}
