import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminContentKeys } from "./keys";

export type AdminHomeCurationSlot = components["schemas"]["AdminHomeCurationSlot"];
type AdminHomeCurationListResponse = components["schemas"]["AdminHomeCurationListResponse"];

/** 유형마다 한 칸(스토리 → 캐릭터 순). 작품 목록 위 현황과 작품 상세의 지정 버튼이 같이 쓴다. */
export function useHomeCurationsQuery() {
  return useQuery<AdminHomeCurationSlot[], ApiError>({
    queryKey: adminContentKeys.homeCurations(),
    queryFn: async () => (await apiClient.get<AdminHomeCurationListResponse>("/admin/home-curations")).data.items,
  });
}
