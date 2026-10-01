import { useQuery } from "@tanstack/react-query";

import { commentApi } from "./commentApi";
import { commentKeys } from "./keys";

export function useCommentStickersQuery() {
  return useQuery({ queryKey: commentKeys.stickers, queryFn: ({ signal }) => commentApi.stickers(signal) });
}
