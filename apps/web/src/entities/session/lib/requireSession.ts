import type { QueryClient } from "@tanstack/react-query";
import { redirect } from "@tanstack/react-router";

import { sessionQueryOptions } from "../api/session-query-options";

/** techspec-auth-onboarding.md §1 — 인증이 필요한 라우트의 `beforeLoad`에서 호출한다.
 * 세션이 없으면(GET /me가 401) 로그인 화면으로 리다이렉트하고 원래 목적지를 보존한다. */
export async function requireSession(queryClient: QueryClient, href: string): Promise<void> {
  try {
    await queryClient.ensureQueryData(sessionQueryOptions);
  } catch {
    throw redirect({ to: "/login", search: { redirect: href } });
  }
}
