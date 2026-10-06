import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";

export type NovelChapterResponse = components["schemas"]["NovelChapterResponse"];
export type NovelRevisionResponse = components["schemas"]["NovelRevisionResponse"];

/** `GET /novels/{novelId}/chapters/{chapterId}` — 장 하나의 현재 본문과 서버가 나눈 문단(`paragraphs`). 문단은
 * 화면이 다시 나누지 않는다 — 문단 범위를 고르는 AI 수정은 서버가 나눈 인덱스로 받으므로, 다르게 나누면 고른
 * 문단과 고쳐지는 문단이 어긋난다.
 *
 * `revisionId` 는 상세가 알려 준 그 장의 현재 개정이다(키에만 쓴다). 새 개정으로 키가 바뀌는 동안에는 같은 장의
 * 직전 본문을 그대로 보여 준다 — 비우면 본문 아래 직접 고치던 입력칸까지 통째로 사라졌다 다시 그려진다. 다른 장의
 * 본문은 이어 보여 주지 않는다. */
export function useNovelChapterQuery(novelId: string, chapterId: string, revisionId: string) {
  return useQuery<NovelChapterResponse, ApiError>({
    queryKey: novelKeys.chapter(novelId, chapterId, revisionId),
    queryFn: async () => (await apiClient.get<NovelChapterResponse>(`/novels/${novelId}/chapters/${chapterId}`)).data,
    placeholderData: (previous) => (previous?.id === chapterId ? previous : undefined),
  });
}
