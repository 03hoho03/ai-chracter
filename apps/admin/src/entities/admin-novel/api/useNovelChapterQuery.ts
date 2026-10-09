import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys } from "./keys";

export type AdminNovelChapterResponse = components["schemas"]["AdminNovelChapterResponse"];

/** 화 공개본 하나 — 독자에게 나가는 그대로. 화를 펼칠 때만 부른다(상세 응답에는 본문이 없다). */
export function useNovelChapterQuery(novelId: string, chapterId: string) {
  return useQuery<AdminNovelChapterResponse, ApiError>({
    queryKey: adminNovelKeys.chapter(novelId, chapterId),
    queryFn: async () =>
      (await apiClient.get<AdminNovelChapterResponse>(`/admin/novels/${novelId}/chapters/${chapterId}`)).data,
  });
}
