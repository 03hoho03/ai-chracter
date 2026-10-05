import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { novelKeys, type NovelDetailResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

type SaveNovelNotesVariables = { novelId: string; settingNotes: string };

/** `PUT /novels/{novelId}/notes` — 설정 노트를 통째로 바꾼다. 응답이 상세 전체라 그것으로 상세 캐시를 바로 덮는다
 * (노트 폼은 상세에서 기준값을 굳히므로, 캐시를 안 고치면 다시 열 때 옛 노트로 굳는다). 목록의 갱신 시각도
 * 바뀌어 목록은 낡았다고 표시한다. */
export function useSaveNovelNotesMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelDetailResponse, ApiError, SaveNovelNotesVariables>({
    mutationFn: async ({ novelId, settingNotes }) =>
      (await apiClient.put<NovelDetailResponse>(`/novels/${novelId}/notes`, { settingNotes })).data,
    onSuccess: (novel) => {
      queryClient.setQueryData(novelKeys.detail(novel.id), novel);
      void queryClient.invalidateQueries({ queryKey: novelKeys.list() });
    },
  });
}
