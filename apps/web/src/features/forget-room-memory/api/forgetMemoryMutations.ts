import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "@/entities/chat-room";
import { apiClient } from "@/shared/api/client";

type ForgetPreviewDto = components["schemas"]["ChatRoomMemoryFactForgetPreview"];

// 잊게 하기는 성공해도 실패해도 목록을 다시 받는다 — 실패의 대부분은 "그 기억이 이미 없다"라 지금 목록이 낡았다는 뜻이다.
// 다시 받기를 기다린 뒤에 끝나게 해(`onSettled` 가 돌려준 약속을 뮤테이션이 기다린다) 확인 대화가 닫힐 때 지운 행이 이미
// 목록에서 빠져 있게 한다.
function useForgetMutation<TVariables>(roomId: string, forget: (variables: TVariables) => Promise<void>) {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, TVariables>({
    mutationFn: forget,
    onSettled: () => queryClient.invalidateQueries({ queryKey: chatRoomKeys.memoryItems(roomId) }),
  });
}

export function useForgetEpisodeMutation(roomId: string) {
  return useForgetMutation(roomId, async (episodeId: string) => {
    await apiClient.delete(`/chat-rooms/${roomId}/memory/episodes/${episodeId}`);
  });
}

export function useForgetFactMutation(roomId: string) {
  return useForgetMutation(roomId, async (factKey: string) => {
    await apiClient.delete(`/chat-rooms/${roomId}/memory/facts`, { params: { key: factKey } });
  });
}

/** 사실 하나를 잊으면 함께 지워질 장면 수. 확인 대화를 열 때마다 새로 묻는다(`staleTime`·`gcTime` 0) — 대화가 이어지는
 * 사이 수가 바뀔 수 있고, 지난번 수를 먼저 그리면 지울 범위를 잘못 알린다. 키는 방 기억 키 아래(로그아웃 정리에 함께
 * 걸린다)지만 목록 키 밖이다 — 잊게 하기가 끝나며 목록을 다시 받을 때 아직 닫히는 중인 확인 대화가 이 수를 다시 묻지 않게.
 * 실패는 곧바로 보인다(`retry` 없음) — 확인 대화가 "다시 확인"을 둔다. */
export function useForgetFactPreviewQuery(roomId: string, factKey: string) {
  return useQuery<ForgetPreviewDto, ApiError>({
    queryKey: [...chatRoomKeys.memory(roomId), "forget-preview", factKey],
    queryFn: async () =>
      (
        await apiClient.get<ForgetPreviewDto>(`/chat-rooms/${roomId}/memory/facts/forget-preview`, {
          params: { key: factKey },
        })
      ).data,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
}
