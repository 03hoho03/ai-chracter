import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { personaKeys } from "./keys";
import type { PersonaList } from "../model/persona";

/** `GET /me/personas` — 목록(생성순)·기본 프로필 id·개수 상한(`maxCount`)을 한 번에 준다. */
export function usePersonasQuery() {
  return useQuery<PersonaList, ApiError>({
    queryKey: personaKeys.list(),
    queryFn: async () => (await apiClient.get<PersonaList>("/me/personas")).data,
  });
}
