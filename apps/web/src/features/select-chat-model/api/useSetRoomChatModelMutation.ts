import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { chatModelKeys, type ChatModelId } from "@/entities/chat-model";
import { applyRoomChatModel, chatRoomKeys, type ChatRoomState } from "@/entities/chat-room";
import { sessionKeys } from "@/entities/session";
import { apiClient } from "@/shared/api/client";

import { isChatModelNotAllowedError } from "../model/chatModelError";

type ChatRoomModelResponse = components["schemas"]["ChatRoomModelResponse"];

/** `PUT /chat-rooms/{id}/model` — 다음 턴부터 쓸 글쓰기 모델. 응답이 방 응답의 같은 이름 칸(유효 모델·그 이름·턴
 * 가격)이라 방 상세 캐시의 그 세 칸만 응답값으로 고친다. invalidate 는 `refetchType: "none"` 으로 낡음 표시만 한다 — 바꾼 세
 * 칸을 위해 메시지 전체를 다시 받지 않는다(`useSetRoomPersonaMutation` 과 같은 이유).
 *
 * 상위 모델 허용이 없다는 403 이면 세션과 모델 목록을 다시 읽는다 — 허용을 거둔 직후의 탭은 옛 `GET /me` 로 더보기의
 * 모델 항목을, 옛 목록으로 상위 모델을 계속 보이므로 이 응답을 계기로 둘 다 거둔다. 결과와 무관하게 일어나야 하는
 * 일이라 호출 단위가 아니라 여기 둔다. */
export function useSetRoomChatModelMutation(roomId: string) {
  const queryClient = useQueryClient();

  return useMutation<ChatRoomModelResponse, ApiError, ChatModelId>({
    mutationFn: async (model) =>
      (await apiClient.put<ChatRoomModelResponse>(`/chat-rooms/${roomId}/model`, { model })).data,
    onSuccess: (data) => {
      queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), (prev) => applyRoomChatModel(prev, data));
      return queryClient.invalidateQueries({ queryKey: chatRoomKeys.detail(roomId), refetchType: "none" });
    },
    onError: (error) => {
      if (!isChatModelNotAllowedError(error)) return;
      void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
      void queryClient.invalidateQueries({ queryKey: chatModelKeys.all });
    },
  });
}
