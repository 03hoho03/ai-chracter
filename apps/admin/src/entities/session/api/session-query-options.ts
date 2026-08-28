import type { components } from "@ai-character-chat/api-types";
import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { sessionKeys } from "./keys";

export type AdminMeResponse = components["schemas"]["AdminMeResponse"];

/** techspec-admin.md §0 — techspec-auth-onboarding.md §1과 동일한 패턴(useSessionQuery
 * 훅 + beforeLoad 라우터 가드가 같은 쿼리 옵션을 공유)을 완전히 별도의 인증 엔드포인트로 재사용한다. */
export const sessionQueryOptions = queryOptions({
  queryKey: sessionKeys.current(),
  queryFn: async () => (await apiClient.get<AdminMeResponse>("/admin/me")).data,
  staleTime: Infinity,
  retry: false,
});
