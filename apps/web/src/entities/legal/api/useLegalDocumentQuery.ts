import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { legalKeys } from "./keys";
import type { LegalDocumentKind } from "../model/legal";

export type LegalDocumentResponse = components["schemas"]["LegalDocumentPublicResponse"];

/** `GET /legal/{kind}` — 공개 조회, 인증 불필요. 게시본이 없으면 404이고 재시도해도 절대
 * 성공하지 않으므로 4xx는 즉시 에러 상태로 넘긴다(entities/profile의 동일 패턴). */
export function useLegalDocumentQuery(kind: LegalDocumentKind, enabled = true) {
  return useQuery<LegalDocumentResponse, ApiError>({
    queryKey: legalKeys.document(kind),
    queryFn: async () => (await apiClient.get<LegalDocumentResponse>(`/legal/${kind}`)).data,
    enabled,
    retry: (failureCount, error) => (error.status === 0 || error.status >= 500) && failureCount < 3,
  });
}
