import type { QueryClient } from "@tanstack/react-query";

import { novelKeys } from "@/entities/novel";

/** 지운 화들의 본문·판 캐시를 버린다. 그 화를 보는 화면이 아직 있으면 부르지 않는다 — 관찰자가 남은 쿼리를 지우면
 * 관찰자가 곧바로 다시 받아 404 가 난다. 그래서 지우기 모달이 아니라 화면이 그 화를 떠난 뒤 호출부가 부른다. */
export function removeDeletedChapterCaches(queryClient: QueryClient, novelId: string, chapterIds: readonly string[]) {
  for (const chapterId of chapterIds) {
    queryClient.removeQueries({ queryKey: novelKeys.chapterAll(novelId, chapterId) });
    queryClient.removeQueries({ queryKey: novelKeys.revisions(novelId, chapterId) });
  }
}
