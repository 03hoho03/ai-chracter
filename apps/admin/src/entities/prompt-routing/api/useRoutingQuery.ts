import { useQuery } from "@tanstack/react-query";

import { routingQueryOptions } from "./routingQueryOptions";

export function useRoutingQuery() {
  return useQuery(routingQueryOptions);
}
