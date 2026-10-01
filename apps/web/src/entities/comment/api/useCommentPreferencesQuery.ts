import { useQuery } from "@tanstack/react-query";

import { commentApi } from "./commentApi";
import { commentKeys } from "./keys";

export function useCommentPreferencesQuery(viewerId: string, enabled: boolean) {
  return useQuery({
    queryKey: commentKeys.preferences(viewerId),
    queryFn: ({ signal }) => commentApi.preferences(signal), enabled,
  });
}
