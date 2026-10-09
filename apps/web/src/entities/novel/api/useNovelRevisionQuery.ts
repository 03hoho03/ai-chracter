import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";
import type { NovelRevisionResponse } from "./useNovelChapterQuery";

/** `GET …/revisions/{revisionId}` — 옛 판 하나의 본문. 판은 만든 뒤 바뀌지 않아 한 번 받으면 다시 묻지 않는다.
 * `revisionId` 가 없으면(펼친 판이 없으면) 묻지 않는다. 판 이력과 버전 비교가 함께 쓰므로 여기 둔다 — 같은 판을 두
 * 화면이 같은 캐시로 읽는다. */
export function useNovelRevisionQuery(novelId: string, chapterId: string, revisionId: string | undefined) {
  return useQuery<NovelRevisionResponse, ApiError>({
    queryKey: novelKeys.revision(novelId, chapterId, revisionId ?? ""),
    queryFn: async () =>
      (
        await apiClient.get<NovelRevisionResponse>(
          `/novels/${novelId}/chapters/${chapterId}/revisions/${revisionId ?? ""}`,
        )
      ).data,
    enabled: revisionId !== undefined,
    staleTime: Infinity,
  });
}
