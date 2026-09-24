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
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: personaKeys.all });
    },
  });
}
