import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import type { ContentType } from "../model/types";
import { contentKeys, type VisibilityFilter } from "./keys";

export type ContentSummary = components["schemas"]["ContentSummary"];

/** techspec-global-nav-profile.md §3.2 — 프로필 작품 목록. 본인 조회일 때만 visibilityFilter를
 * 넘긴다(타인 조회는 서버가 무시하므로 굳이 생략할 필요는 없지만, 필터 UI 자체가 본인에게만 노출된다). */
export function useProfileContentListQuery({
  userId,
  type,
  visibilityFilter,
}: {
  userId: string;
  type: ContentType;
  visibilityFilter?: VisibilityFilter;
}) {
  return useQuery<ContentSummary[], ApiError>({
    queryKey: contentKeys.list(userId, type, visibilityFilter),
    queryFn: async () =>
      (
        await apiClient.get<ContentSummary[]>(`/users/${userId}/contents`, {
          params: { type, visibility: visibilityFilter },
        })
      ).data,
  });
}
