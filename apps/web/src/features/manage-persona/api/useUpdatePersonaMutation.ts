import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "@/entities/chat-room";
import { personaKeys, type Persona } from "@/entities/persona";
import { apiClient } from "@/shared/api/client";

type PersonaUpsertRequest = components["schemas"]["PersonaUpsertRequest"];

export function useUpdatePersonaMutation() {
  const queryClient = useQueryClient();

  return useMutation<Persona, ApiError, { personaId: string; payload: PersonaUpsertRequest }>({
    mutationFn: async ({ personaId, payload }) =>
      (await apiClient.put<Persona>(`/me/personas/${personaId}`, payload)).data,
    onSuccess: () => {
      // 방 상세는 프로필 이름을 함께 싣는다(작가 글의 `{{user}}` 자리). 어느 방이 이 프로필을 쓰는지 FE 는 모르므로
      // 방 상세를 전부 낡았다고 표시한다 — 이름 한 칸이 낡았을 뿐 방은 그대로라 remove 가 아니다.
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.details() });
      // Promise를 반환해 `mutateAsync`가 목록 refetch까지 기다리게 한다 — 폼이 닫힌 뒤 옛 값이 보이지 않게.
      return queryClient.invalidateQueries({ queryKey: personaKeys.all });
    },
  });
}
