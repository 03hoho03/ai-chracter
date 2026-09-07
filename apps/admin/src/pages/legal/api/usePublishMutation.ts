import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { LegalKind } from "../model/legalKind";
import { legalKeys } from "./keys";
import type { AdminLegalDocumentResponse } from "./useLegalDocumentQuery";

export type AdminLegalPublishRequest = components["schemas"]["AdminLegalPublishRequest"];

/** POST .../publish는 현재 초안의 본문을 새 게시본으로 만든다 — 초안은 그대로 남는다.
 * 응답으로 detail 캐시를 바로 채우고, 새 버전이 하나 추가된 이력만 invalidate한다. */
export function usePublishMutation(kind: LegalKind) {
  const queryClient = useQueryClient();

  return useMutation<AdminLegalDocumentResponse, ApiError, AdminLegalPublishRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminLegalDocumentResponse>(`/admin/legal/${kind}/publish`, payload)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(legalKeys.detail(kind), data);
      void queryClient.invalidateQueries({ queryKey: legalKeys.versions(kind) });
    },
  });
}
