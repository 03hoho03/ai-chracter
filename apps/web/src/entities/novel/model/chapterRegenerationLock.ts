import type { NovelDetailResponse } from "../api/useNovelQuery";

/** 그 화를 다시 만드는 작업이 진행 중일 때 직접 고치기·저장·판 되돌리기 대신 보이는 사유. */
export const CHAPTER_REGENERATING_MESSAGE = "이 화를 다시 만드는 중이에요. 끝나면 고치거나 되돌릴 수 있어요.";

/** 이 화를 다시 만드는 작업이 진행 중인가. 그동안에는 이 화의 직접 저장·판 되돌리기를 막는다 — 다시 만든 글은
 * 기준 판을 보지 않고 그때의 최신 판 위에 쌓여서, 그사이 저장한 글은 몇 분 뒤 판 이력으로 밀려난다.
 *
 * 다시 만들기는 한 번에 만든 화들(묶음) 전체를 새로 쓰므로, 작업이 가리키는 묶음에 이 화가 들어 있으면 고른 화가
 * 아니어도 잠근다. 작업에 묶음이 없으면(옛 화 단위 작업) 작업이 가리키는 화로 판단한다. 다른 묶음의 재생성·새 화
 * 만들기·남은 대화 한 번에·AI 수정은 이 화의 현재 판을 바꾸지 않아 막지 않는다. */
export function isChapterRegenerating(
  activeJob: NovelDetailResponse["activeJob"],
  chapterId: string,
  batchId: string | undefined,
): boolean {
  if (activeJob?.kind !== "chapter_regenerate") return false;
  if (activeJob.batchId !== null) return activeJob.batchId === batchId;
  return activeJob.chapterId === chapterId;
}
