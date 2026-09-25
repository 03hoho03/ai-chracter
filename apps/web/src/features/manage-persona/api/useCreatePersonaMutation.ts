import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { personaKeys, type Persona } from "@/entities/persona";
import { apiClient, isApiError } from "@/shared/api/client";

type PersonaCreateRequest = components["schemas"]["PersonaCreateRequest"];

/** 생성은 `defaultPersonaId`를 바꿀 수 있어(`setAsDefault`) 목록 캐시를 통째로 다시 읽는다. */
export function useCreatePersonaMutation() {
  const queryClient = useQueryClient();

  return useMutation<Persona, ApiError, PersonaCreateRequest>({
    mutationFn: async (payload) => (await apiClient.post<Persona>("/me/personas", payload)).data,
    onSuccess: () =>
      // Promise를 반환해 `mutateAsync`가 목록 refetch까지 기다리게 한다 — 폼이 닫힌 뒤 옛 목록(빈 상태·옛
      // `defaultPersonaId`)이 한 왕복 동안 보이지 않게.
      queryClient.invalidateQueries({ queryKey: personaKeys.all }),
    // 409 = 다른 경로(탭·방 모달)에서 이미 상한까지 찼다 — 캐시의 개수가 낡았다는 뜻이라 다시 읽는다. 안 그러면
    // 폼을 닫아도 `9/10개`·`새 프로필` 활성으로 남아 또 409를 받는다.
    onError: async (error) => {
      if (isApiError(error) && error.status === 409) await queryClient.invalidateQueries({ queryKey: personaKeys.all });
    },
  });
}
