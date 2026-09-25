import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { personaKeys } from "@/entities/persona";
import { apiClient } from "@/shared/api/client";

/** `PUT /me/default-persona` — `null`이면 기본 해제. **방 상세는 invalidate하지 않는다**: BE
 * `set_default_persona`는 `users.default_persona_id`만 바꾸고 기존 방은 건드리지 않는다(기본
 * 지정은 소급되지 않는다). 기본은 새 방을 만들 때만 읽힌다. */
export function useSetDefaultPersonaMutation() {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, string | null>({
    mutationFn: async (personaId) => {
      await apiClient.put("/me/default-persona", { personaId });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: personaKeys.all });
    },
  });
}
