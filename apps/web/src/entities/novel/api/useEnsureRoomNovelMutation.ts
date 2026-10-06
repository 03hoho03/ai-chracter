import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";
import type { NovelDetailResponse } from "./useNovelQuery";

/** `POST /chat-rooms/{roomId}/novel` — 그 방의 소설을 돌려준다. 없으면 만들고(201) 있으면 그대로 준다(200).
 * 과금은 없다. 소설 주소는 방이 아니라 소설 id 라(방을 지워도 소설은 남는다) 방에서 들어갈 때 이 호출로 id 를
 * 얻는다.
 *
 * 응답이 상세 전체라 상세 캐시를 먼저 채워 둔다 — 이동한 화면이 로딩 상태 없이 바로 그려진다. 새로 만들어졌을
 * 수 있으니 목록은 낡았다고 표시만 한다. 둘 다 결과와 무관하게 항상 일어나야 할 일이라 호출부가 아니라 여기에
 * 둔다. */
export function useEnsureRoomNovelMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelDetailResponse, ApiError, string>({
    mutationFn: async (roomId) => (await apiClient.post<NovelDetailResponse>(`/chat-rooms/${roomId}/novel`)).data,
    onSuccess: (novel) => {
      queryClient.setQueryData(novelKeys.detail(novel.id), novel);
      void queryClient.invalidateQueries({ queryKey: novelKeys.list() });
    },
  });
}
