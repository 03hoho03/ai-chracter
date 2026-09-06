import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { legalKeys, type LegalKind } from "./keys";

export type AdminLegalDocumentResponse = components["schemas"]["AdminLegalDocumentResponse"];

export function useLegalDocumentQuery(kind: LegalKind) {
  return useQuery<AdminLegalDocumentResponse, ApiError>({
    queryKey: legalKeys.detail(kind),
    queryFn: async () => (await apiClient.get<AdminLegalDocumentResponse>(`/admin/legal/${kind}`)).data,
  });
}
