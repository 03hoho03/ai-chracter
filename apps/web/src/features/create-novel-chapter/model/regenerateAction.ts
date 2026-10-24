import { isNovelOutlineFlowOn, isOutlineFlowChapter, type NovelChapterSummary } from "@/entities/novel";

/** 구성 흐름 스위치를 아는가 — 켜짐·꺼짐·아직 모름(가격 응답을 받는 중). */
export type OutlineFlowAvailability = "on" | "off" | "loading";

/** 가격 응답의 구성 흐름 스위치. 응답을 받기 전이면 아직 모른다. */
export function toOutlineFlowAvailability(
  pricing: Parameters<typeof isNovelOutlineFlowOn>[0],
): OutlineFlowAvailability {
  if (pricing === undefined) return "loading";
  return isNovelOutlineFlowOn(pricing) ? "on" : "off";
}

/** 화 패널의 다시 만들기가 무엇을 하는가. 대화로 바로 만든 화는 그 화가 든 묶음을 옛 라우트로, 구성안으로 쓴 화는 그 화를 같은 장면
 * 구성안으로 새 라우트로 다시 쓴다(서버가 서로의 화를 409 로 거절한다). 구성 흐름 스위치가 꺼지면 새 라우트가 404 라 구성안으로 쓴 화는
 * 다시 만들 수 없다 — 이유를 말한다. 스위치를 아직 모르면 이유 없이 기다린다(잠깐 사이 틀린 이유를 말하지 않게). */
export type RegenerateAction =
  | { kind: "batch"; batchId: string }
  | { kind: "outline"; chapterId: string }
  | { kind: "unavailable"; reason: string | undefined };

export const OUTLINE_FLOW_OFF_REGENERATE_REASON = "구성 흐름이 꺼져 있어 지금은 다시 만들 수 없어요.";

export function toRegenerateAction(
  chapter: Pick<NovelChapterSummary, "id" | "batchId"> & Partial<Pick<NovelChapterSummary, "episodeOutlineId">>,
  outlineFlow: OutlineFlowAvailability,
): RegenerateAction {
  if (!isOutlineFlowChapter(chapter)) return { kind: "batch", batchId: chapter.batchId };
  if (outlineFlow === "on") return { kind: "outline", chapterId: chapter.id };
  return { kind: "unavailable", reason: outlineFlow === "off" ? OUTLINE_FLOW_OFF_REGENERATE_REASON : undefined };
}
