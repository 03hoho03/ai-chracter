import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { chatModelKeys } from "./keys";

export type ChatModel = components["schemas"]["ChatModelItem"];

/** `GET /chat-models` — 이 계정이 채팅방에 고를 수 있는 모델과 한 턴의 클로버. 기본 모델(Gemini)은 언제나 맨 앞에
 * 있고, 상위 모델은 채팅 상위 모델 허용이 있을 때만 실린다. 허용은 어드민이 세션 중에도 바꿀 수 있어 staleTime 을
 * 두지 않는다 — 선택 모달을 열 때마다 다시 묻는다(권위는 모델을 바꾸는 요청이 403 으로 지킨다). */
export function useChatModelsQuery() {
  return useQuery<ChatModel[], ApiError>({
    queryKey: chatModelKeys.all,
    queryFn: async () => (await apiClient.get<ChatModel[]>("/chat-models")).data,
  });
}
