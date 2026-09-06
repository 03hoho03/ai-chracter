import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { legalKeys, type LegalKind } from "./keys";

export type AdminLegalVersionsResponse = components["schemas"]["AdminLegalVersionsResponse"];

export function useVersionsQuery(kind: LegalKind) {
  return useQuery<AdminLegalVersionsResponse, ApiError>({
    queryKey: legalKeys.versions(kind),
    queryFn: async () => (await apiClient.get<AdminLegalVersionsResponse>(`/admin/legal/${kind}/versions`)).data,
  });
}
