import type { components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { sessionKeys } from "./keys";

export type MeResponse = components["schemas"]["MeResponse"];

export function useSessionQuery() {
  return useQuery({
    queryKey: sessionKeys.current(),
    queryFn: async () => (await apiClient.get<MeResponse>("/me")).data,
    staleTime: Infinity,
    retry: false,
  });
}
