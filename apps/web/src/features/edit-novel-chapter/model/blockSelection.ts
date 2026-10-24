import type { NovelRevisionScene } from "@/entities/novel";

import type { ParagraphRange } from "./paragraphRange";

/** 여러 문단 고르기의 판단 재료. 고른 것은 블록 id 목록이고(누른 차례 — 마지막이 Shift 이어 고르기의 시작점), 문단 인덱스는
 * 지금 판의 블록 차례다. */
export type BlockSelectionContext = {
  /** 지금 판의 블록 id(문단 차례). */
  blockIds: readonly string[];
  sceneKeyOf: (blockId: string) => string;
  /** 상세의 `limits.blockEditMaxBlocks`. */
  maxBlocks: number;
  /** 그 문단을 고를 수 있는가 — 수정안이 놓인 자리는 버튼이 아니다. */
  isSelectable: (index: number) => boolean;
};

/** 고르기 한 번의 결과. 고른 것이 바뀌지 않았으면 왜인지(`outsideScene`·`limit`)를 알린다. */
export type BlockSelectionOutcome = "added" | "removed" | "outsideScene" | "limit" | "ignored";
export type BlockSelectionStep = { selection: string[]; outcome: BlockSelectionOutcome };

const WHOLE_CHAPTER = "chapter";

/** 장면 하나의 열쇠. 고르기와 장면 머리줄이 같은 값으로 장면을 가리킨다. */
export function toSceneKey(sceneId: string): string {
  return `scene:${sceneId}`;
}

/** 블록 → 장면 열쇠. 서버의 "같은 장면" 판정과 같은 읽기다 — 개정의 `scenes` 가 비었으면(장면 경계가 없는 화) 화 전체가 한
 * 장면이고, 아니면 그 블록이 든 장면이다. 목록에 없는 블록은 어느 장면과도 묶지 않는다(서버 422 를 미리 막는 쪽으로 접는다). */
export function toSceneKeyOf(revision: {
  blocks: readonly { id: string }[];
  scenes: readonly NovelRevisionScene[];
}): (blockId: string) => string {
  if (revision.scenes.length === 0) return () => WHOLE_CHAPTER;
  const sceneByBlock = new Map<string, string>();
  for (const scene of revision.scenes) {
    for (const blockId of scene.blockIds) sceneByBlock.set(blockId, toSceneKey(scene.id));
  }
  return (blockId) => sceneByBlock.get(blockId) ?? `block:${blockId}`;
}

/** 문단 하나를 눌렀을 때의 다음 고른 것.
 *
 * - 누르면 켜고, 고른 문단을 다시 누르면 끈다. 떨어진 문단도 함께 고른다.
 * - 이미 고른 문단과 다른 장면이면 켜지 않는다(`outsideScene`). 다 풀면 어느 장면이든 새로 고를 수 있다.
 * - 상한만큼 골랐으면 더 켜지 않는다(`limit`). 끄는 것은 된다.
 * - `extend`(Shift+누르기·Shift+Enter)는 마지막으로 고른 문단부터 누른 문단까지 같은 장면 안의 고를 수 있는 문단을 모두 켠다
 *   — 끄지 않는다. 상한에 닿으면 시작점에 가까운 쪽부터 거기까지만 켜고 `limit` 을 알린다. */
export function nextBlockSelection(
  selection: readonly string[],
  index: number,
  { extend = false }: { extend?: boolean },
  context: BlockSelectionContext,
): BlockSelectionStep {
  const blockId = context.blockIds[index];
  if (blockId === undefined || !context.isSelectable(index)) return { selection: [...selection], outcome: "ignored" };
  const anchorId = selection.at(-1);
  const anchorIndex = anchorId === undefined ? -1 : context.blockIds.indexOf(anchorId);
  if (selection.includes(blockId) && !extend) {
    return { selection: selection.filter((id) => id !== blockId), outcome: "removed" };
  }
  const sceneKey = selection[0] === undefined ? undefined : context.sceneKeyOf(selection[0]);
  if (sceneKey !== undefined && context.sceneKeyOf(blockId) !== sceneKey) {
    return { selection: [...selection], outcome: "outsideScene" };
  }
  if (!extend || anchorIndex < 0) {
    if (selection.includes(blockId)) return { selection: [...selection], outcome: "added" };
    if (selection.length >= context.maxBlocks) return { selection: [...selection], outcome: "limit" };
    return { selection: [...selection, blockId], outcome: "added" };
  }
  const next = [...selection];
  const direction = index >= anchorIndex ? 1 : -1;
  for (let cursor = anchorIndex; cursor !== index + direction; cursor += direction) {
    const id = context.blockIds[cursor];
    if (id === undefined || next.includes(id) || !context.isSelectable(cursor)) continue;
    if (context.sceneKeyOf(id) !== context.sceneKeyOf(blockId)) continue;
    if (next.length >= context.maxBlocks) return { selection: next, outcome: "limit" };
    next.push(id);
  }
  return { selection: next, outcome: "added" };
}

/** 고른 블록의 문단 인덱스(본문 차례). 지금 판에 없는 블록(다른 곳의 수정으로 지워진 문단)은 뺀다. */
export function toSelectedIndexes(selection: readonly string[], blockIds: readonly string[]): number[] {
  return selection
    .map((id) => blockIds.indexOf(id))
    .filter((index) => index >= 0)
    .sort((a, b) => a - b);
}

/** 고르지 않은 문단이 지금 왜 고를 수 없는가. 고른 것과 다른 장면이면 `outsideScene`, 상한만큼 골랐으면 `limit`. */
export function toBlockBlockedReason(
  index: number,
  selection: readonly string[],
  context: Pick<BlockSelectionContext, "blockIds" | "sceneKeyOf" | "maxBlocks">,
): "outsideScene" | "limit" | undefined {
  const blockId = context.blockIds[index];
  const first = selection[0];
  if (blockId === undefined || first === undefined || selection.includes(blockId)) return undefined;
  if (context.sceneKeyOf(blockId) !== context.sceneKeyOf(first)) return "outsideScene";
  return selection.length >= context.maxBlocks ? "limit" : undefined;
}

/** "3번째 문단" / "3·5·7번째 문단" / "2~4·7번째 문단". 이어진 문단은 물결로 접는다(스무 개를 하나씩 읽지 않게). 화면 번호는 1부터다. */
export function formatParagraphIndexes(indexes: readonly number[]): string {
  const runs: string[] = [];
  let start: number | undefined;
  let previous: number | undefined;
  for (const index of [...indexes, Number.NaN]) {
    if (start !== undefined && previous !== undefined && index === previous + 1) {
      previous = index;
      continue;
    }
    if (start !== undefined && previous !== undefined) runs.push(start === previous ? `${start + 1}` : `${start + 1}~${previous + 1}`);
    start = index;
    previous = index;
  }
  return `${runs.join("·")}번째 문단`;
}

/** 확인 창·지시 창이 부르는 이름. 둘 이상이면 개수를 붙인다("3·5·7번째 문단 3개"). */
export function toBlockSelectionLabel(indexes: readonly number[]): string {
  const label = formatParagraphIndexes(indexes);
  return indexes.length > 1 ? `${label} ${indexes.length}개` : label;
}

/** 고르기를 알리는 한 줄(`aria-live`). 고른 것을 말하고, 바뀌지 않았으면 그 까닭을 말한다. */
export function toBlockSelectionAnnouncement(
  indexes: readonly number[],
  outcome: BlockSelectionOutcome,
  maxBlocks: number,
): string {
  if (outcome === "outsideScene") return "같은 장면 안의 문단만 함께 고를 수 있어요.";
  const chosen = toChosenSentence(indexes);
  return outcome === "limit" ? `${chosen} 한 번에 ${maxBlocks}개 문단까지 고를 수 있어요.` : chosen;
}

function toChosenSentence(indexes: readonly number[]): string {
  if (indexes.length === 0) return "고른 문단이 없어요.";
  if (indexes.length === 1) return `${formatParagraphIndexes(indexes)}을 골랐어요.`;
  return `${formatParagraphIndexes(indexes)}, ${indexes.length}개를 골랐어요.`;
}

/** 고른 문단이 이어져 있으면 그 범위 — 직접 고치기·그림 붙이기는 이어진 문단에만 된다. */
export function toContiguousRange(indexes: readonly number[]): ParagraphRange | null {
  const start = indexes[0];
  const end = indexes.at(-1);
  if (start === undefined || end === undefined || end - start + 1 !== indexes.length) return null;
  return { start, end };
}

/** 목적격 조사를 붙인다 — 끝 글자에 받침이 있으면 "을", 없으면 "를"(한글이 아니면 "을"). */
export function withObjectParticle(label: string): string {
  const last = label.at(-1);
  const code = last === undefined ? -1 : last.charCodeAt(0) - 0xac00;
  const hasFinal = code < 0 || code > 11171 || code % 28 !== 0;
  return `${label}${hasFinal ? "을" : "를"}`;
}
