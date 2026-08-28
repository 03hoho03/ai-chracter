import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { contentKeys } from "./keys";

export type GenreResponse = components["schemas"]["GenreResponse"];

/** techspec-home-discovery.md §1 — 장르 마스터 10종(sort_order 순으로 이미 정렬되어 옴). 시딩 마이그레이션
 * 외에는 바뀌지 않는 데이터라 매 마운트마다 다시 불러올 필요가 없다. */
export function useGenreListQuery() {
  return useQuery<GenreResponse[], ApiError>({
    queryKey: contentKeys.genres(),
    queryFn: async () => (await apiClient.get<GenreResponse[]>("/genres")).data,
    staleTime: Infinity,
  });
}
