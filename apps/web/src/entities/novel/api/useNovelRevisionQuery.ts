import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";
import type { NovelRevisionResponse } from "./useNovelChapterQuery";

/** 판 응답을 다시 묻기까지의 시간. 판 글은 바뀌지 않지만 함께 오는 삽화의 서명 주소는 15분 창마다 바뀌어(창의 두 배 동안
 * 유효) 오래 둔 응답의 그림이 깨지고, 그림 내림 상태도 바뀐다 — 창보다 짧게 둔다. */
const REVISION_STALE_MS = 10 * 60 * 1000;

/** `GET …/revisions/{revisionId}` — 옛 판 하나의 본문. 판 글은 만든 뒤 바뀌지 않지만 삽화 칸(서명 주소·내림 상태) 때문에
 * 일정 시간 뒤에는 다시 묻는다. `revisionId` 가 없으면(펼친 판이 없으면) 묻지 않는다. 판 이력과 버전 비교가 함께 쓰므로
 * 여기 둔다 — 같은 판을 두 화면이 같은 캐시로 읽는다. */
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
    staleTime: REVISION_STALE_MS,
  });
}
