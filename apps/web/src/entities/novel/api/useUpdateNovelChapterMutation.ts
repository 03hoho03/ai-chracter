import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";
import type { NovelDetailResponse } from "./useNovelQuery";

export type NovelChapterUpdateRequest = components["schemas"]["NovelChapterUpdateRequest"];

/** `PATCH /novels/{novelId}/chapters/{chapterId}` — 화 제목·작가의 말(보낸 칸만, 무과금). 제목을 보내면 고친 제목이
 * 되어 다시 만들기가 덮지 않고, 제목에 `null` 을 보내면 비워서 다음 다시 만들기가 AI 제목을 다시 쓴다. 바꾸지 않는 칸은
 * 빼고 보낸다(서버가 `null` 과 부재를 가른다). 응답이 상세 전체라 그것으로 상세 캐시를 바로 덮고, 목록은 갱신 시각이
 * 바뀌어 낡았다. 본문은 개정 경로로 고치므로 본문 캐시는 그대로다. */
export function useUpdateNovelChapterMutation() {
  const queryClient = useQueryClient();
  return useMutation<NovelDetailResponse, ApiError, { novelId: string; chapterId: string; body: NovelChapterUpdateRequest }>({
    mutationFn: async ({ novelId, chapterId, body }) =>
      (await apiClient.patch<NovelDetailResponse>(`/novels/${novelId}/chapters/${chapterId}`, body)).data,
    onSuccess: (novel) => {
      queryClient.setQueryData(novelKeys.detail(novel.id), novel);
      void queryClient.invalidateQueries({ queryKey: novelKeys.list() });
    },
  });
}
