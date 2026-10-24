import type { NovelEpisodeOutlineState, NovelEpisodeOutlineView, NovelOutlineEpisode } from "@/entities/novel";

/** 전체 구성안 화 하나의 장면 구성안 상태 — 그 화의 가장 최근 판으로 정한다(승인본 위 새 초안은 초안, 그 판이 낡았으면 낡음). */
export type SceneOutlineStatus = NovelOutlineEpisode["sceneOutline"];

export const SCENE_OUTLINE_STATUS_LABEL: Record<SceneOutlineStatus, string> = {
  none: "장면 구성안 없음",
  draft: "장면 구성안 초안",
  approved: "장면 구성안 승인됨",
  stale: "장면 구성안 낡음",
};

/** 원고 상태 — 이미 쓴 화(그 화로 가는 길), 쓸 차례, 앞 화를 먼저 써야 함, 뒤 화에 이미 원고가 있어 쓸 수 없음. */
export type ManuscriptStatus =
  | { kind: "written"; chapterId: string }
  | { kind: "next" }
  | { kind: "waiting" }
  | { kind: "laterWritten" };

export const MANUSCRIPT_STATUS_LABEL: Record<ManuscriptStatus["kind"], string> = {
  written: "원고 있음",
  next: "쓸 차례",
  waiting: "앞 화 먼저",
  laterWritten: "뒤 화에 원고 있음",
};

/** 구성안 화마다의 원고 상태. 서버는 원고가 구성안 맨 앞부터 이어지게만 쓴다 — 앞 화가 모두 원고이고 뒤 화는 원고가 아니어야 쓸 수
 * 있다. 그래서 첫 빈 화가 쓸 차례이고, 그 뒤 빈 화는 앞 화 먼저다. 구성안을 고쳐 원고 있는 화가 빈 화 뒤로 갔으면 그 빈 화는 쓸 수
 * 없다(드문 경우). */
export function toManuscriptStatuses(episodes: readonly Pick<NovelOutlineEpisode, "chapterId">[]): ManuscriptStatus[] {
  return episodes.map((episode, index) => {
    if (episode.chapterId !== null) return { kind: "written", chapterId: episode.chapterId };
    if (episodes.slice(index + 1).some((later) => later.chapterId !== null)) return { kind: "laterWritten" };
    if (episodes.slice(0, index).every((earlier) => earlier.chapterId !== null)) return { kind: "next" };
    return { kind: "waiting" };
  });
}

/** 보드 개요 입구의 셋째 단계 한 줄. */
export function toManuscriptProgressLine(episodes: readonly Pick<NovelOutlineEpisode, "chapterId">[]): string {
  const written = episodes.filter((episode) => episode.chapterId !== null).length;
  return `화별 장면·원고 · 원고 ${written.toLocaleString()}/${episodes.length.toLocaleString()}화`;
}

/** 화 화면이 보여 주고 고치기 시작할 판. 초안(승인하지 않은 최신 판)이 늘 승인본보다 새 판이라 먼저다. */
export function toEpisodeOutlineBase(
  state: NovelEpisodeOutlineState,
): { view: NovelEpisodeOutlineView; status: "draft" | "approved"; isStale: boolean } | undefined {
  if (state.draft !== null) return { view: state.draft, status: "draft", isStale: state.draft.stale };
  if (state.approved !== null) return { view: state.approved, status: "approved", isStale: state.approved.stale };
  return undefined;
}

/** 지금 승인한 전체 구성안의 상태 — 없음·낡음·쓸 수 있음. 장면 구성안과 원고는 승인하고 낡지 않은 전체 구성안의 화로만 만든다. */
export type ApprovedOutlineStatus = "missing" | "stale" | "ok";

/** 장면 구성안 만들기·다시 만들기(유료)를 지금 못 누르는 이유. 앞에 있는 것이 먼저다. 이유가 없으면 누를 수 있다. */
export function toSceneMakeBlockedReason(status: {
  isRoomGone: boolean;
  isJobRunning: boolean;
  isAiEditRunning: boolean;
  outline: ApprovedOutlineStatus;
  /** 이 화의 원고가 있는가 — 원고가 된 화는 서버가 장면 구성안을 새로 만들지 않는다. */
  isWritten: boolean;
  isDirty: boolean;
}): string | undefined {
  if (status.isRoomGone) return "원래 대화방이 지워져 장면 구성안을 새로 만들 수 없어요.";
  if (status.isJobRunning) return "다른 작업이 끝나면 만들 수 있어요.";
  if (status.isAiEditRunning) return "AI로 고치는 중이에요. 끝나면 만들 수 있어요.";
  if (status.outline === "missing") return "전체 구성안을 먼저 승인해주세요.";
  if (status.outline === "stale") return "전체 구성안이 낡아 장면 구성안을 만들 수 없어요. 전체 구성안을 먼저 바로잡아주세요.";
  if (status.isWritten) return "원고를 쓴 화는 장면 구성안을 새로 만들지 않아요.";
  if (status.isDirty) return "고친 장면 구성안을 먼저 저장하거나 되돌려주세요.";
  return undefined;
}

/** 원고 쓰기(유료)를 지금 못 누르는 이유. 앞에 있는 것이 먼저다 — 방·작업처럼 기다리거나 못 푸는 것, 그다음 전체 구성안, 원고 차례(앞
 * 화를 써야 풀리는 쪽), 그 화의 장면 구성안 순이다. 승인하지 않은 새 초안이 있으면 막는다 — 서버는 옛 승인 판으로 쓰지만, 화면에 보이는
 * 판과 다른 판으로 클로버를 쓰지 않게 한다. */
export function toWriteBlockedReason(status: {
  isRoomGone: boolean;
  isJobRunning: boolean;
  isAiEditRunning: boolean;
  outline: ApprovedOutlineStatus;
  order: Exclude<ManuscriptStatus["kind"], "written">;
  hasApproved: boolean;
  hasNewerDraft: boolean;
  isApprovedStale: boolean;
  isDirty: boolean;
}): string | undefined {
  if (status.isRoomGone) return "원래 대화방이 지워져 원고를 쓸 수 없어요.";
  if (status.isJobRunning) return "다른 작업이 끝나면 쓸 수 있어요.";
  if (status.isAiEditRunning) return "AI로 고치는 중이에요. 끝나면 쓸 수 있어요.";
  if (status.outline === "missing") return "전체 구성안을 먼저 승인해주세요.";
  if (status.outline === "stale") return "전체 구성안이 낡아 원고를 쓸 수 없어요. 전체 구성안을 먼저 바로잡아주세요.";
  if (status.order === "waiting") return "앞 화 원고를 먼저 써주세요.";
  if (status.order === "laterWritten") return "뒤 화에 원고가 있어 이 화는 쓸 수 없어요.";
  if (!status.hasApproved) return "장면 구성안을 승인하면 원고를 쓸 수 있어요.";
  if (status.hasNewerDraft) return "승인하지 않은 새 장면 구성안이 있어요. 승인한 뒤 원고를 쓸 수 있어요.";
  if (status.isApprovedStale) return "장면 구성안이 낡았어요. 다시 만들어 승인한 뒤 원고를 쓸 수 있어요.";
  if (status.isDirty) return "고친 장면 구성안을 먼저 저장하고 승인해주세요.";
  return undefined;
}
