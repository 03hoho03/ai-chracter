import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { personaKeys, type Persona } from "@/entities/persona";
import { apiClient } from "@/shared/api/client";

type PersonaUpsertRequest = components["schemas"]["PersonaUpsertRequest"];

export function useUpdatePersonaMutation() {
  const queryClient = useQueryClient();

  return useMutation<Persona, ApiError, { personaId: string; payload: PersonaUpsertRequest }>({
    mutationFn: async ({ personaId, payload }) =>
      (await apiClient.put<Persona>(`/me/personas/${personaId}`, payload)).data,
    onSuccess: () =>
      // Promise를 반환해 `mutateAsync`가 목록 refetch까지 기다리게 한다 — 폼이 닫힌 뒤 옛 값이 보이지 않게.
      queryClient.invalidateQueries({ queryKey: personaKeys.all }),
  });
}
