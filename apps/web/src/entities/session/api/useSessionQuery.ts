import { useQuery } from "@tanstack/react-query";

import { sessionQueryOptions } from "./sessionQueryOptions";

export type { MeResponse } from "./sessionQueryOptions";

export function useSessionQuery() {
  return useQuery(sessionQueryOptions);
}
