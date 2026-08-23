import type { QueryClient } from "@tanstack/react-query";
import { redirect } from "@tanstack/react-router";

import type { MeResponse } from "../api/session-query-options";
import { sessionQueryOptions } from "../api/session-query-options";

/** techspec-auth-onboarding.md §1 — 인증이 필요한 라우트의 `beforeLoad`에서 호출한다.
 * 세션이 없으면(GET /me가 401) 로그인 화면으로 리다이렉트하고 원래 목적지를 보존한다.
 *
 * 돌려주는 값은 그대로 라우트 컨텍스트에 병합되므로, 로그인한 사용자 자신의 id가 필요한 라우트는
 * `Route.useRouteContext().session`으로 **좁힘 없이** 읽을 수 있다(US-008 `/my`). */
export async function requireSession(
  queryClient: QueryClient,
  href: string,
): Promise<{ session: MeResponse }> {
  try {
    return { session: await queryClient.ensureQueryData(sessionQueryOptions) };
  } catch {
    throw redirect({ to: "/login", search: { redirect: href } });
  }
}
