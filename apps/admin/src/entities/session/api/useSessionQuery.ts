import { useQuery } from "@tanstack/react-query";

import { sessionQueryOptions } from "./session-query-options";

export type { AdminMeResponse } from "./session-query-options";

export function useSessionQuery() {
  return useQuery(sessionQueryOptions);
}
