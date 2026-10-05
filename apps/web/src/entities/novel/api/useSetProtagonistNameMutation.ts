import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";
import type { NovelDetailResponse } from "./useNovelQuery";

type SetProtagonistNameVariables = { novelId: string; protagonistName: string };

/** `PUT /novels/{novelId}/protagonist-name` — 소설 속 주인공(이용자 쪽) 이름. 응답이 상세 전체라 그것으로 상세
 * 캐시를 바로 덮는다 — 이름을 정한 직후 이어지는 장 만들기가 낡은 "이름 없음"을 다시 보지 않게. 이미 만든 장
 * 본문은 서버가 바꾸지 않는다. */
export function useSetProtagonistNameMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelDetailResponse, ApiError, SetProtagonistNameVariables>({
    mutationFn: async ({ novelId, protagonistName }) =>
      (await apiClient.put<NovelDetailResponse>(`/novels/${novelId}/protagonist-name`, { protagonistName })).data,
    onSuccess: (novel) => {
      queryClient.setQueryData(novelKeys.detail(novel.id), novel);
    },
  });
}
