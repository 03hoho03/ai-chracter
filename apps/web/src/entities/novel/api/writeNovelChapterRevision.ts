import type { QueryClient } from "@tanstack/react-query";

import { novelKeys } from "./keys";
import type { NovelChapterResponse } from "./useNovelChapterQuery";
import type { NovelDetailResponse } from "./useNovelQuery";

/** 장에 새 개정이 생긴 응답(직접 수정·되돌리기·AI 수정 적용 — 셋 다 201 + 장 전체)을 캐시에 쓴다.
 *
 * - 장 본문은 응답으로 바로 채운다. 다시 받게 두면 저장 직후 옛 본문이 한 번 칠해진다.
 * - 상세의 그 장 목차 정보(현재 개정)도 응답으로 고친다 — 장 본문 캐시의 키가 상세의 현재 개정 id 라, 상세를
 *   고치지 않으면 다시 받기 전까지 화면이 옛 키(옛 본문)를 본다. 그 장의 미적용 AI 수정안도 함께 뺀다. 서버도 기준
 *   개정이 바뀐 수정안을 목록에서 빼고 적용을 막는다.
 * - 그래도 상세(갱신 시각·다른 장)와 개정 목록은 낡았으니 다시 받게 표시한다. */
export function writeNovelChapterRevision(queryClient: QueryClient, chapter: NovelChapterResponse) {
  const { novelId, id: chapterId, revision } = chapter;
  queryClient.setQueryData(novelKeys.chapter(novelId, chapterId, revision.id), chapter);
  queryClient.setQueryData<NovelDetailResponse>(novelKeys.detail(novelId), (novel) =>
    novel === undefined
      ? undefined
      : {
          ...novel,
          chapters: novel.chapters.map((summary) =>
            summary.id === chapterId
              ? {
                  ...summary,
                  currentRevisionId: revision.id,
                  currentRevisionNo: revision.revisionNo,
                  currentRevisionSource: revision.source,
                  updatedAt: revision.createdAt,
                }
              : summary,
          ),
          pendingAiEdits: novel.pendingAiEdits.filter((edit) => edit.chapterId !== chapterId),
        },
  );
  void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
  void queryClient.invalidateQueries({ queryKey: novelKeys.revisions(novelId, chapterId) });
  void queryClient.invalidateQueries({ queryKey: novelKeys.list() });
}
