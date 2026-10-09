import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { webnovelKeys } from "./keys";

export type WebnovelChapterResponse = components["schemas"]["PublicNovelChapterResponse"];

/** `GET /webnovels/{novelId}/chapters/{chapterId}` — 화 하나. 읽을 수 있으면 공개본 본문을 문단 배열로, 잠겼으면
 * 본문 없이 가격만 싣는다(`access: "locked"`). 본문을 내줄 때 서버가 조회 수를 센다(회원마다 하루 한 번). */
export function useWebnovelChapterQuery(novelId: string, chapterId: string) {
  return useQuery<WebnovelChapterResponse, ApiError>({
    queryKey: webnovelKeys.chapter(novelId, chapterId),
    queryFn: async () =>
      (await apiClient.get<WebnovelChapterResponse>(`/webnovels/${novelId}/chapters/${chapterId}`)).data,
  });
}
