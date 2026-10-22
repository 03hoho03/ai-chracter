import type { QueryClient } from "@tanstack/react-query";

import { novelKeys } from "./keys";
import type { NovelChapterResponse } from "./useNovelChapterQuery";
import type { NovelDetailResponse } from "./useNovelQuery";

/** 장에 새 개정이 생긴 응답(직접 수정·되돌리기·AI 수정 적용 — 모두 201 + 장 전체)을 캐시에 쓴다.
 *
 * - 장 본문은 응답으로 바로 채운다. 다시 받게 두면 저장 직후 옛 본문이 한 번 칠해진다.
 * - 상세의 그 장 목차 정보(현재 개정)도 응답으로 고친다 — 장 본문 캐시의 키가 상세의 현재 개정 id 라, 상세를
 *   고치지 않으면 다시 받기 전까지 화면이 옛 키(옛 본문)를 본다.
 * - 그 장의 미적용 AI 수정안은 새 판의 글이 직전 판 글과 다를 때만 뺀다. 서버는 글이 바뀐 수정안만 목록에서 빼고 적용을
 *   막으므로, 같은 글의 새 판(삽화만 바꾼 판·같은 글 판으로 되돌림)에서 빼면 상세를 다시 받을 때 되살아나 깜빡인다. 상세에
 *   실린 수정안은 늘 지금 판과 글이 같은 것뿐이라 "새 판 글 = 직전 판 글"이 서버 판정과 같은 답이다. 직전 판 본문을 캐시에
 *   갖고 있지 않으면 뺀다 — 남기면 적용이 충돌로 끝나는 낡은 수정안이 한 번 보인다. 수정안을 적용한 응답이면
 *   (`appliedEditId`) 그 수정안은 글이 같아도 뺀다 — 서버가 적용한 작업을 목록에서 빼므로 남기면 다시 적용할 수 없는 카드가
 *   보인다(고칠 곳이 없어 글이 그대로인 수정안).
 * - 그래도 상세(갱신 시각·다른 장)와 개정 목록은 낡았으니 다시 받게 표시한다. */
export function writeNovelChapterRevision(
  queryClient: QueryClient,
  chapter: NovelChapterResponse,
  { appliedEditId }: { appliedEditId?: string } = {},
) {
  const { novelId, id: chapterId, revision } = chapter;
  const isSameText = isSameAsPreviousText(queryClient, chapter);
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
          pendingAiEdits: novel.pendingAiEdits.filter(
            (edit) => edit.id !== appliedEditId && (isSameText || edit.chapterId !== chapterId),
          ),
        },
  );
  void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
  void queryClient.invalidateQueries({ queryKey: novelKeys.revisions(novelId, chapterId) });
  void queryClient.invalidateQueries({ queryKey: novelKeys.list() });
}

/** 새 판의 문단이 상세가 알던 직전 판의 문단과 같은가. 직전 판 본문 캐시가 없으면 거짓이다. 문단 배열로 견준다 — 서버의
 * 글 판정도 문단을 빈 줄 하나로 다시 이은 글의 해시라 같은 답이다. */
function isSameAsPreviousText(queryClient: QueryClient, chapter: NovelChapterResponse): boolean {
  const previousId = queryClient
    .getQueryData<NovelDetailResponse>(novelKeys.detail(chapter.novelId))
    ?.chapters.find((summary) => summary.id === chapter.id)?.currentRevisionId;
  if (previousId === undefined) return false;
  const previous = queryClient.getQueryData<NovelChapterResponse>(novelKeys.chapter(chapter.novelId, chapter.id, previousId));
  if (previous === undefined) return false;
  const next = chapter.revision.paragraphs;
  return (
    previous.revision.paragraphs.length === next.length &&
    previous.revision.paragraphs.every((text, index) => text === next[index])
  );
}
