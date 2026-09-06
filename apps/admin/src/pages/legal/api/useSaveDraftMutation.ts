import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { legalKeys, type LegalKind } from "./keys";
import type { AdminLegalDocumentResponse } from "./useLegalDocumentQuery";

export type AdminLegalDraftUpsertRequest = components["schemas"]["AdminLegalDraftUpsertRequest"];

/** PUT .../draft는 게시본을 건드리지 않고 초안만 upsert한다(T-12) — 응답이 이미 최신
 * 전체 문서라 invalidate 대신 setQueryData로 캐시를 바로 채운다. */
export function useSaveDraftMutation(kind: LegalKind) {
  const queryClient = useQueryClient();

  return useMutation<AdminLegalDocumentResponse, ApiError, AdminLegalDraftUpsertRequest>({
    mutationFn: async (payload) =>
      (await apiClient.put<AdminLegalDocumentResponse>(`/admin/legal/${kind}/draft`, payload)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(legalKeys.detail(kind), data);
    },
  });
}
