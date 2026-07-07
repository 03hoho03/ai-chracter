import type { components } from "@ai-character-chat/api-types";
import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { sessionKeys } from "./keys";

export type MeResponse = components["schemas"]["MeResponse"];

/** techspec-auth-onboarding.md §1 — 세션도 서버 상태이므로 useQuery(훅)와
 * beforeLoad 라우터 가드(ensureQueryData) 양쪽이 동일한 옵션을 공유한다. */
export const sessionQueryOptions = queryOptions({
  queryKey: sessionKeys.current(),
  queryFn: async () => (await apiClient.get<MeResponse>("/me")).data,
  staleTime: Infinity,
  retry: false,
});
