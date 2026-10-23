import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys } from "./keys";

export type AdminNovelChapterResponse = components["schemas"]["AdminNovelChapterResponse"];
export type AdminNovelIllustration = components["schemas"]["AdminNovelIllustration"];
export type AdminNovelChapterEditionItem = components["schemas"]["AdminNovelChapterEditionItem"];

/** 화의 판 하나 — 그 판을 산 회원에게 나가는 그대로. 화를 펼칠 때만 부른다(상세 응답에는 본문이 없다). `edition` 이 `null` 이면
 * 판 번호 없이 지금 판을 부른다. */
export function useNovelChapterQuery(novelId: string, chapterId: string, edition: number | null) {
  return useQuery<AdminNovelChapterResponse, ApiError>({
    queryKey: adminNovelKeys.chapter(novelId, chapterId, edition),
    queryFn: async () =>
      (
        await apiClient.get<AdminNovelChapterResponse>(`/admin/novels/${novelId}/chapters/${chapterId}`, {
          params: edition === null ? undefined : { edition },
        })
      ).data,
  });
}
