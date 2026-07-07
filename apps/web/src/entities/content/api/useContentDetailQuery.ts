import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { contentKeys } from "./keys";

export type ContentDetailResponse = components["schemas"]["ContentDetailResponse"];

/** techspec-content-detail.md §2 — 상세화면(모달/풀페이지 공용). 로그인 여부와 무관하게 호출 가능하며,
 * 응답에 담긴 accessStatus/isOwner로 접근 가능 여부를 판정한다(별도 403/404 가드 없음). */
export function useContentDetailQuery(id: string) {
  return useQuery<ContentDetailResponse, ApiError>({
    queryKey: contentKeys.detail(id),
    queryFn: async () => (await apiClient.get<ContentDetailResponse>(`/contents/${id}`)).data,
  });
}
