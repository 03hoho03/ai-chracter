import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { contentKeys } from "./keys";

export type ContentVersionSummary = components["schemas"]["ContentVersionSummary"];

/** techspec-content-detail.md §6, US-017 — 조회 전용 버전 이력(전환 액션 없음). `enabled`로
 * VersionHistoryModal이 열렸을 때만 조회한다(상세화면 진입 시 바로 필요한 데이터가 아님). */
export function useContentVersionsQuery(id: string, enabled: boolean) {
  return useQuery<ContentVersionSummary[], ApiError>({
    queryKey: contentKeys.versions(id),
    queryFn: async () => (await apiClient.get<ContentVersionSummary[]>(`/contents/${id}/versions`)).data,
    enabled,
  });
}
