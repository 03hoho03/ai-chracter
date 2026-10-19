import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cloverKeys } from "@/entities/clover";
import { novelKeys, type NovelPublicationStatus } from "@/entities/novel";
import { webnovelKeys } from "@/entities/webnovel";
import { apiClient } from "@/shared/api/client";

/** `POST /novels/{id}/publication/chapters/{chapterId}/free` — 공개한 유료 화를 무료로 바꾼다(되돌릴 수 없다). 응답이
 * 공개 상태라 그대로 캐시에 쓴다. 독자 화면의 목차·가격이 낡으므로 노벨 캐시는 낡았다고 표시한다. 실패하면 공개 상태를
 * 다시 받는다 — 그사이 화를 지웠거나 스위치가 꺼져 화면이 낡았을 수 있다. 스위치는 가격 응답이 말하므로 그것도 다시
 * 받는다(안 그러면 꺼진 뒤에도 목록과 전환 버튼이 남는다). */
export function useMakeChapterFreeMutation(novelId: string) {
  const queryClient = useQueryClient();
  return useMutation<NovelPublicationStatus, ApiError, string>({
    mutationFn: async (chapterId) =>
      (await apiClient.post<NovelPublicationStatus>(`/novels/${novelId}/publication/chapters/${chapterId}/free`)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(novelKeys.publication(novelId), data);
      void queryClient.invalidateQueries({ queryKey: webnovelKeys.all });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: novelKeys.publication(novelId) });
      void queryClient.invalidateQueries({ queryKey: cloverKeys.pricing() });
    },
  });
}
