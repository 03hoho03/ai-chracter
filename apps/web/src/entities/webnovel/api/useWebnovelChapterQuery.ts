import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { webnovelKeys } from "./keys";

export type WebnovelChapterResponse = components["schemas"]["PublicNovelChapterResponse"];

/** `GET /webnovels/{novelId}/chapters/{chapterId}` — 화 하나. 읽을 수 있으면 공개본 본문을 문단 배열로, 잠겼으면
 * 본문 없이 가격만 싣는다(`access: "locked"`). 본문을 내줄 때 서버가 조회 수를 센다(회원마다 하루 한 번).
 *
 * `edition` 은 소장자가 고른 산 때의 판이다(없으면 최신 판). 서버는 지금 판과 그 사람의 산 때의 판만 주고 그 밖은
 * 404 이며, 정책 스위치가 꺼져 있으면 이 값을 보지 않고 지금 판을 준다. */
export function useWebnovelChapterQuery(novelId: string, chapterId: string, edition?: number) {
  return useQuery<WebnovelChapterResponse, ApiError>({
    queryKey: webnovelKeys.chapterEdition(novelId, chapterId, edition),
    queryFn: async () =>
      (
        await apiClient.get<WebnovelChapterResponse>(`/webnovels/${novelId}/chapters/${chapterId}`, {
          params: edition === undefined ? undefined : { edition },
        })
      ).data,
  });
}
