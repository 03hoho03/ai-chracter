import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import type { ContentType } from "../model/content";
import type { VisibilityFilter } from "../model/visibilityFilter";
import { contentKeys } from "./keys";

export type ContentSummary = components["schemas"]["ContentSummary"];
export type ContentSummaryListResponse = components["schemas"]["ContentSummaryListResponse"];

/** techspec-global-nav-profile.md §3.2 — 프로필 작품 목록. 본인 조회일 때만 visibilityFilter를
 * 넘긴다(타인 조회는 서버가 무시하므로 굳이 생략할 필요는 없지만, 필터 UI 자체가 본인에게만 노출된다).
 *
 * US-001로 커서 페이징이 들어가 응답이 `{ items, nextCursor }` 봉투가 됐다. 여기서는 첫 페이지(24건)만
 * 읽는다 — `nextCursor`를 실제로 따라가는 "더 보기"는 US-009가 붙인다. */
export function useProfileContentListQuery({
  userId,
  type,
  visibilityFilter,
}: {
  userId: string;
  type: ContentType;
  visibilityFilter?: VisibilityFilter;
}) {
  return useQuery<ContentSummaryListResponse, ApiError>({
    queryKey: contentKeys.list(userId, type, visibilityFilter),
    queryFn: async () =>
      (
        await apiClient.get<ContentSummaryListResponse>(`/users/${userId}/contents`, {
          params: { type, visibility: visibilityFilter },
        })
      ).data,
  });
}
