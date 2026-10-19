import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { legalKeys } from "./keys";
import type { LegalDocumentKind } from "../model/legal";

type LegalUpcomingDocumentResponse = components["schemas"]["LegalUpcomingDocumentResponse"];

/** `GET /legal/{kind}/upcoming` — 시행 예정 판의 전문, 인증 불필요. 예정 판이 없으면 404 라 4xx 는 다시 묻지 않는다.
 * 전문이 수만 자라 화면이 "예정 전문 보기"를 펼칠 때만 켠다(`enabled`). */
export function useLegalUpcomingDocumentQuery(kind: LegalDocumentKind, enabled: boolean) {
  return useQuery<LegalUpcomingDocumentResponse, ApiError>({
    queryKey: legalKeys.upcoming(kind),
    queryFn: async () => (await apiClient.get<LegalUpcomingDocumentResponse>(`/legal/${kind}/upcoming`)).data,
    enabled,
    retry: (failureCount, error) => (error.status === 0 || error.status >= 500) && failureCount < 3,
  });
}
