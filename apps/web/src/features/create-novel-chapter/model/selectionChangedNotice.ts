import { hasNovelErrorCode, type NovelAction, type NovelJobResponse } from "@/entities/novel";

/** 승인한 담을 대화의 원문이 고른 뒤 바뀌어 거절된 요청인가. 담을 대화를 확인해 다시 승인해야 풀린다. */
export function isSelectionChangedRefusal(error: unknown): boolean {
  return hasNovelErrorCode(error, "NOVEL_SOURCE_SELECTION_SOURCE_CHANGED");
}

/** 그 거절 뒤 담을 대화가 있는 구성 문서로 돌아가야 하는가. 장면 구성안·원고는 화 하나의 화면에서 시작하는데, 그 화면에는 바뀐 구간도
 * 담을 대화로 가는 길도 없다. 전체 구성안은 이미 담을 대화와 같은 문서라 옮기지 않는다. */
export function shouldReturnToSelection(error: unknown, action: NovelAction): boolean {
  return (action === "episodeOutline" || action === "outlineChapter") && isSelectionChangedRefusal(error);
}

/** 승인한 담을 대화의 원문이 바뀌어 실패한 구성 흐름 작업인가(서버가 실행 중에 같은 검사로 실패시키고 돌려준다). 옛 화 만들기의 원문
 * 바뀜은 담을 대화와 무관해 다시 승인해도 풀리지 않는다. */
export function isSelectionChangedFailure(job: Pick<NovelJobResponse, "kind" | "failureReason">): boolean {
  if (job.failureReason !== "source_changed") return false;
  return job.kind === "outline_generate" || job.kind === "episode_outline_generate" || job.kind === "outline_chapter_generate";
}

/** 담을 대화를 다시 승인한 뒤의 작업 줄 안내 — 담을 대화 탓의 오류는 원인이 풀려 지우고, 다른 안내는 그대로 둔다. */
export function withoutSelectionChangedNotice<T extends { tone: "error" | "done"; isSelectionChanged?: boolean }>(
  notice: T | undefined,
): T | undefined {
  return notice?.tone === "error" && notice.isSelectionChanged === true ? undefined : notice;
}
