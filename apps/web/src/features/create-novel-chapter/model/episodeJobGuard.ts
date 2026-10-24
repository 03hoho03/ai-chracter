import type { NovelEpisodeOutlineState } from "@/entities/novel";

/** 장면 구성안 만들기·원고 쓰기를 확인 창 앞에서 멈출 이유. 화 화면의 버튼은 같은 이유로 이미 막지만, 작업 줄의 "다시 시도"는 그 화면을
 * 거치지 않고 이 흐름을 바로 연다 — 그래서 확인 직전에 새로 받은 상태와 그 화의 고치던 것으로 한 번 더 본다. 원고는 서버가 옛 승인
 * 판으로 쓰더라도 화면에 보이는 판과 다른 판으로 클로버를 쓰지 않게 막는다. 이유가 없으면 진행한다. */
export function toEpisodeJobRefusal(
  kind: "episodeOutline" | "outlineChapter",
  state: Pick<NovelEpisodeOutlineState, "approved" | "draft">,
  isEditing: boolean,
): string | undefined {
  if (isEditing) {
    return kind === "episodeOutline"
      ? "고친 장면 구성안을 먼저 저장하거나 되돌려주세요."
      : "고친 장면 구성안을 먼저 저장하고 승인해주세요.";
  }
  if (kind === "episodeOutline") return undefined;
  if (state.draft !== null) return "승인하지 않은 새 장면 구성안이 있어요. 승인한 뒤 원고를 쓸 수 있어요.";
  if (state.approved === null) return "장면 구성안을 승인한 뒤 원고를 쓸 수 있어요.";
  if (state.approved.stale) return "장면 구성안이 낡았어요. 다시 만들어 승인한 뒤 원고를 쓸 수 있어요.";
  return undefined;
}
