import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { LegalKind } from "../model/legalKind";
import { legalKeys } from "./keys";
import type { AdminLegalVersionsResponse } from "./useVersionsQuery";

/** POST .../versions/{version}/withdraw 는 시행 예정 판을 철회하고 갱신된 이력을 돌려준다 — 이력은 응답으로 바로 채우고,
 * 예정 판이 사라진 상단 요약(detail)만 다시 불러온다. 실패해도 둘 다 다시 불러온다: 철회가 거부되는 경우(이미 시행됨·
 * 이미 철회됨)는 화면이 서버보다 낡았다는 뜻이다. */
export function useWithdrawMutation(kind: LegalKind) {
  const queryClient = useQueryClient();

  return useMutation<AdminLegalVersionsResponse, ApiError, string>({
    mutationFn: async (version) =>
      (
        await apiClient.post<AdminLegalVersionsResponse>(
          `/admin/legal/${kind}/versions/${encodeURIComponent(version)}/withdraw`,
        )
      ).data,
    onSuccess: (data) => {
      queryClient.setQueryData(legalKeys.versions(kind), data);
      void queryClient.invalidateQueries({ queryKey: legalKeys.detail(kind) });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: legalKeys.detail(kind) });
      void queryClient.invalidateQueries({ queryKey: legalKeys.versions(kind) });
    },
  });
}
