import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { novelKeys } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

export type NovelBundleRecheckResponse = components["schemas"]["NovelBundleRecheckResponse"];

type RecheckBundleVariables = {
  novelId: string;
  jobId: string;
  bundleId: string;
};

/** `POST /novels/{novelId}/jobs/{jobId}/bundles/{bundleId}/recheck` — 사용자가 묶음 원소의 문단을 고친 뒤 남은 수정안을 따로 적용해도
 * 되는지 묻는다(무료, 시간당 상한, 몸 없음). 따로 적용해도 되면 서버가 고친 원소를 묶음에서 빼므로 상세를 다시 받아 단독 적용이
 * 생긴 모습을 그린다 — 다시 받기를 기다린 뒤 끝내, 그사이 옛 묶음의 다시 검사를 한 번 더 누를 틈을 두지 않는다. 아니라는 판정이면
 * 묶음은 그대로다. */
export function useRecheckBundleMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelBundleRecheckResponse, ApiError, RecheckBundleVariables>({
    mutationFn: async ({ novelId, jobId, bundleId }) =>
      (await apiClient.post<NovelBundleRecheckResponse>(`/novels/${novelId}/jobs/${jobId}/bundles/${bundleId}/recheck`)).data,
    onSuccess: async ({ separable }, { novelId }) => {
      if (separable) await queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
    },
  });
}
