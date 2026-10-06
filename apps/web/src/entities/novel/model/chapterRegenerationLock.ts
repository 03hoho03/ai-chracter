import type { NovelDetailResponse } from "../api/useNovelQuery";

/** 그 장을 다시 만드는 작업이 진행 중일 때 직접 고치기·저장·판 되돌리기 대신 보이는 사유. */
export const CHAPTER_REGENERATING_MESSAGE = "이 장을 다시 만드는 중이에요. 끝나면 고치거나 되돌릴 수 있어요.";

/** 이 장을 다시 만드는 작업이 진행 중인가. 그동안에는 이 장의 직접 저장·판 되돌리기를 막는다 — 다시 만든 글은
 * 기준 판을 보지 않고 그때의 최신 판 위에 쌓여서, 그사이 저장한 글은 몇 분 뒤 판 이력으로 밀려난다. 다른 장의
 * 재생성·새 장 만들기·AI 수정은 이 장의 현재 판을 바꾸지 않아 막지 않는다. */
export function isChapterRegenerating(activeJob: NovelDetailResponse["activeJob"], chapterId: string): boolean {
  return activeJob?.kind === "chapter_regenerate" && activeJob.chapterId === chapterId;
}
