import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { legalKeys } from "./keys";
import type { LegalDocumentKind } from "../model/legal";

type LegalChangesResponse = components["schemas"]["LegalChangesResponse"];

/** `GET /legal/{kind}/changes` — 시행된 판 전부의 변경 안내(최신 판부터), 인증 불필요.
 *
 * `since` 를 넘기지 않는다. 재동의 화면은 동의 단위가 둘이면 둘 중 더 오래된 판을 골라야 하는데 그 앞뒤는 이 목록 안의 위치로만
 * 정할 수 있어서, 전부 받아 `selectChangesSinceOldestConsent` 로 자른다. 공개 문서 화면의 변경 이력과 같은 캐시를 쓴다. */
export function useLegalChangesQuery(kind: LegalDocumentKind, enabled = true) {
  return useQuery<LegalChangesResponse, ApiError>({
    queryKey: legalKeys.changes(kind),
    queryFn: async () => (await apiClient.get<LegalChangesResponse>(`/legal/${kind}/changes`)).data,
    enabled,
    retry: (failureCount, error) => (error.status === 0 || error.status >= 500) && failureCount < 3,
  });
}
