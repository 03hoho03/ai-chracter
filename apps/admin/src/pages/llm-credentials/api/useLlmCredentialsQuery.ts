import { useQuery } from "@tanstack/react-query";

import { llmCredentialsQueryOptions } from "./llmCredentialsQueryOptions";

export function useLlmCredentialsQuery() {
  return useQuery(llmCredentialsQueryOptions);
}
