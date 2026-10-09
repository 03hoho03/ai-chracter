import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys } from "./keys";

export type AdminHomeNovelCurationSlot = components["schemas"]["AdminHomeNovelCurationSlot"];
type AdminHomeNovelCurationListResponse = components["schemas"]["AdminHomeNovelCurationListResponse"];

/** 홈 노벨 자리 1부터 끝까지 — 빈 자리도 한 줄씩 온다. 노벨 목록 위 현황과 노벨 상세의 지정 칸이 같이 쓴다. */
export function useHomeNovelCurationsQuery() {
  return useQuery<AdminHomeNovelCurationSlot[], ApiError>({
    queryKey: adminNovelKeys.homeCurations(),
    queryFn: async () =>
      (await apiClient.get<AdminHomeNovelCurationListResponse>("/admin/home-novel-curations")).data.items,
  });
}
