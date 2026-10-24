import type { NovelOutlineState, NovelOutlineView } from "@/entities/novel";

/** 전체 구성안 단계의 판 상태. 초안(승인하지 않은 최신 판) · 승인됨(최신 판이 승인본). 판이 없으면 비었다. */
export type OutlineStatus = "draft" | "approved";

export const OUTLINE_STATUS_LABEL: Record<OutlineStatus, string> = {
  draft: "초안",
  approved: "승인됨",
};

/** 화면이 보여 주고 고치기 시작할 판. 초안은 늘 승인본보다 새 판이라 초안이 먼저다. `isStale` 은 그 판이 근거로 쓴 구간이 지금
 * 승인한 담을 대화에서 빠졌는가다 — 낡은 판은 고치거나 승인할 수 없다. */
export function toOutlineBase(
  state: NovelOutlineState,
): { view: NovelOutlineView; status: OutlineStatus; isStale: boolean } | undefined {
  if (state.draft !== null) return { view: state.draft, status: "draft", isStale: state.draft.stale };
  if (state.approved !== null) return { view: state.approved, status: "approved", isStale: state.approved.stale };
  return undefined;
}

/** 구성안 만들기·다시 만들기(유료)를 지금 못 누르는 이유. 앞에 있는 것이 먼저다 — 방이 없으면 다른 이유가 풀려도 못 만들고, 작업이
 * 돌면 다른 작업이 끝나야 한다. 이유가 없으면 누를 수 있다(준비 중인지는 호출부가 따로 본다). */
export function toMakeBlockedReason(status: {
  isRoomGone: boolean;
  isJobRunning: boolean;
  isAiEditRunning: boolean;
  /** 담을 대화의 승인 여부. 아직 받는 중이면 `undefined` 다. */
  hasApprovedSelection: boolean | undefined;
  isDirty: boolean;
}): string | undefined {
  if (status.isRoomGone) return "원래 대화방이 지워져 구성안을 새로 만들 수 없어요.";
  if (status.isJobRunning) return "다른 작업이 끝나면 만들 수 있어요.";
  if (status.isAiEditRunning) return "AI로 고치는 중이에요. 끝나면 만들 수 있어요.";
  if (status.hasApprovedSelection === undefined) return "담을 대화를 확인하는 중이에요.";
  if (!status.hasApprovedSelection) return "담을 대화를 먼저 승인해주세요.";
  if (status.isDirty) return "고친 구성안을 먼저 저장하거나 되돌려주세요.";
  return undefined;
}

/** 구성안 화마다 붙일 화 번호. 원고가 있는 화는 그 화 번호이고, 나머지는 구성안 밖의 화(옛 흐름으로 쓴 화)의 마지막 번호 다음부터
 * 구성안 차례대로다 — 원고는 구성안 차례대로만 쓰므로 그 번호가 된다. */
export function toEpisodeOrdinals(
  episodes: readonly { chapterId: string | null }[],
  chapters: readonly { id: string; ordinal: number }[],
): number[] {
  const outlineChapterIds = new Set(episodes.flatMap((episode) => (episode.chapterId === null ? [] : [episode.chapterId])));
  const lastOutside = Math.max(0, ...chapters.filter((chapter) => !outlineChapterIds.has(chapter.id)).map((chapter) => chapter.ordinal));
  return episodes.map(
    (episode, index) => chapters.find((chapter) => chapter.id === episode.chapterId)?.ordinal ?? lastOutside + index + 1,
  );
}
