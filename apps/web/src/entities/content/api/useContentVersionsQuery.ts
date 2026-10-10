import type { ApiError, components } from "@ai-character-chat/api-types";
import { queryOptions, useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { contentKeys } from "./keys";

export type ContentVersionSummary = components["schemas"]["ContentVersionSummary"];

/** 발행된 버전 이력(`GET /contents/{id}/versions`). 한 번도 발행하지 않은 작품은 빈 목록이다. 화면 밖에서
 * `queryClient.fetchQuery` 로 읽는 자리(빌더의 첫 발행 판정)와 같은 키·함수를 쓰려고 옵션으로 둔다. */
export function contentVersionsQueryOptions(id: string) {
  return queryOptions<ContentVersionSummary[], ApiError>({
    queryKey: contentKeys.versions(id),
    queryFn: async () => (await apiClient.get<ContentVersionSummary[]>(`/contents/${id}/versions`)).data,
  });
}

/** 조회 전용 버전 이력(전환 액션 없음). `enabled`로
 * VersionHistoryModal이 열렸을 때만 조회한다(상세화면 진입 시 바로 필요한 데이터가 아님). */
export function useContentVersionsQuery(id: string, enabled: boolean) {
  return useQuery({ ...contentVersionsQueryOptions(id), enabled });
}
