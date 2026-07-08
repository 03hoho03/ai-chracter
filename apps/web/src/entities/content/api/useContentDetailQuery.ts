import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { contentKeys } from "./keys";

export type ContentDetailResponse = components["schemas"]["ContentDetailResponse"];

/** techspec-content-detail.md §2 — 상세화면(모달/풀페이지 공용). 로그인 여부와 무관하게 호출 가능하며,
 * 응답에 담긴 accessStatus/isOwner로 접근 가능 여부를 판정한다(별도 403/404 가드 없음). `enabled`는
 * id를 아직 모르는 시점(예: 챗룸 조회가 끝나야 contentId를 아는 화면, US-055)에 조회를 미루는 용도. */
export function useContentDetailQuery(id: string, enabled = true) {
  return useQuery<ContentDetailResponse, ApiError>({
    queryKey: contentKeys.detail(id),
    queryFn: async () => (await apiClient.get<ContentDetailResponse>(`/contents/${id}`)).data,
    enabled,
  });
}
