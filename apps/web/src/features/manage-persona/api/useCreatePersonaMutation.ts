import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { personaKeys, type Persona } from "@/entities/persona";
import { apiClient } from "@/shared/api/client";

type PersonaCreateRequest = components["schemas"]["PersonaCreateRequest"];

/** 생성은 `defaultPersonaId`를 바꿀 수 있어(UP-23 `setAsDefault`) 목록 캐시를 통째로 다시 읽는다. */
export function useCreatePersonaMutation() {
  const queryClient = useQueryClient();

  return useMutation<Persona, ApiError, PersonaCreateRequest>({
    mutationFn: async (payload) => (await apiClient.post<Persona>("/me/personas", payload)).data,
    onSuccess: () =>
      // Promise를 반환해 `mutateAsync`가 목록 refetch까지 기다리게 한다 — 폼이 닫힌 뒤 옛 목록(빈 상태·옛
      // `defaultPersonaId`)이 한 왕복 동안 보이지 않게(review-s7.md ⚪-1).
      queryClient.invalidateQueries({ queryKey: personaKeys.all }),
  });
}
