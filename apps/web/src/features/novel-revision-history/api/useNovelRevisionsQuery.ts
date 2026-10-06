import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { novelKeys } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

export type NovelRevisionSummary = components["schemas"]["NovelRevisionSummary"];

/** `GET …/chapters/{chapterId}/revisions` — 그 장의 판 목록(최신 먼저, 본문 없음). 맨 앞이 지금 판이다. */
export function useNovelRevisionsQuery(novelId: string, chapterId: string) {
  return useQuery<NovelRevisionSummary[], ApiError>({
    queryKey: novelKeys.revisions(novelId, chapterId),
    queryFn: async () =>
      (
        await apiClient.get<components["schemas"]["NovelRevisionListResponse"]>(
          `/novels/${novelId}/chapters/${chapterId}/revisions`,
        )
      ).data.items,
  });
}
