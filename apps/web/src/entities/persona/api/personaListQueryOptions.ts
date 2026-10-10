import type { ApiError } from "@ai-character-chat/api-types";
import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { personaKeys } from "./keys";
import type { PersonaList } from "../model/persona";

/** `GET /me/personas` — 화면 밖(새 방을 열기 직전)에서 목록을 기다려야 하는 곳도 같은 키·함수를 쓰게 옵션으로 둔다. */
export function personaListQueryOptions() {
  return queryOptions<PersonaList, ApiError>({
    queryKey: personaKeys.list(),
    queryFn: async () => (await apiClient.get<PersonaList>("/me/personas")).data,
  });
}
