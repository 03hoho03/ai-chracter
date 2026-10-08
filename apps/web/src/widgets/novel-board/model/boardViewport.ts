import { NOTES_NODE_KEY, type BoardModel, type BoardNode } from "./boardNode";

/** 처음 화면(저장한 화면 위치가 없을 때)에 맞출 노드 — 마지막 묶음 셋의 화와 설정 노트. 100화 전체에 맞추면 카드가
 * 읽히지 않는 배율이 되고, 다음 묶음을 만들고 고치는 자리는 대개 끝이다. 화가 없으면 노트만이다. */
export const INITIAL_FIT_BATCH_COUNT = 3;

export function toInitialFitNodeIds(nodes: readonly BoardNode[], model: BoardModel): { id: string }[] {
  const lastBatchIds = new Set(
    [...model.batches]
      .sort((a, b) => a.ordinal - b.ordinal)
      .slice(-INITIAL_FIT_BATCH_COUNT)
      .map((batch) => batch.id),
  );
  return nodes
    .filter((node) => node.id === NOTES_NODE_KEY || (node.type === "episode" && lastBatchIds.has(node.data.batchId)))
    .map((node) => ({ id: node.id }));
}

type Rect = { x: number; y: number; width: number; height: number };
type Viewport = { x: number; y: number; zoom: number };

/** 캔버스 좌표의 상자가 지금 화면 안에 통째로 보이는가. 고른 카드(목록·뒤로 가기·새 화 완성으로 바뀐 것)가 화면
 * 밖이면 그 카드로 옮길지 정하는 데 쓴다. 화면 크기를 아직 모르면(0) 보인다고 본다 — 옮길 기준이 없다. */
export function isRectInView(rect: Rect, viewport: Viewport, size: { width: number; height: number }): boolean {
  if (size.width <= 0 || size.height <= 0) return true;
  const left = rect.x * viewport.zoom + viewport.x;
  const top = rect.y * viewport.zoom + viewport.y;
  const right = left + rect.width * viewport.zoom;
  const bottom = top + rect.height * viewport.zoom;
  return left >= 0 && top >= 0 && right <= size.width && bottom <= size.height;
}
