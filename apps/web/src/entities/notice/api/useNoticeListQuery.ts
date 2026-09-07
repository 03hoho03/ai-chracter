import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { noticeKeys } from "./keys";

export type NoticeListItem = components["schemas"]["NoticeListItem"];
export type NoticeListResponse = components["schemas"]["NoticeListResponse"];

/** `GET /notices` — 공개 목록, 인증 불필요. 항목이 제목+날짜뿐이라 페이징하지 않는다(D-13) —
 * 응답에 `nextCursor`가 없으므로 `useQuery` 하나로 충분하다. */
export function useNoticeListQuery() {
  return useQuery<NoticeListResponse, ApiError>({
    queryKey: noticeKeys.list(),
    queryFn: async () => (await apiClient.get<NoticeListResponse>("/notices")).data,
    retry: (failureCount, error) => (error.status === 0 || error.status >= 500) && failureCount < 3,
  });
}
