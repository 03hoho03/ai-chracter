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
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: personaKeys.all });
    },
  });
}
