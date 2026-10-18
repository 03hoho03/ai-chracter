import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { LegalKind } from "../model/legalKind";
import { legalKeys } from "./keys";
import type { AdminLegalDocumentResponse } from "./useLegalDocumentQuery";

export type AdminLegalPublishRequest = components["schemas"]["AdminLegalPublishRequest"];

/** POST .../publish는 현재 초안의 본문·변경 안내를 새 게시본으로 만든다 — 초안 본문은 그대로 남고 초안의 변경 안내는
 * 서버가 비운다(다음 판에 낡은 안내가 복제되지 않게). 응답으로 detail 캐시를 바로 채우고, 새 버전이 하나 추가된 이력만
 * invalidate한다. 409(시행 예정 판이 있음 등)는 화면이 서버보다 낡았을 수 있어 둘 다 다시 불러온다. */
export function usePublishMutation(kind: LegalKind) {
  const queryClient = useQueryClient();

  return useMutation<AdminLegalDocumentResponse, ApiError, AdminLegalPublishRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminLegalDocumentResponse>(`/admin/legal/${kind}/publish`, payload)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(legalKeys.detail(kind), data);
      void queryClient.invalidateQueries({ queryKey: legalKeys.versions(kind) });
    },
    onError: (error) => {
      if (error.status !== 409) return;
      void queryClient.invalidateQueries({ queryKey: legalKeys.detail(kind) });
      void queryClient.invalidateQueries({ queryKey: legalKeys.versions(kind) });
    },
  });
}
