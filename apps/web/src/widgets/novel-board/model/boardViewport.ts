import { NOTES_NODE_KEY, type BoardModel, type BoardNode } from "./boardNode";

/** 처음 화면(저장한 화면 위치가 없을 때)에 맞출 노드 — 끝에서부터 묶음 단위로, 화가 `INITIAL_FIT_MAX_EPISODES` 를
 * 넘지 않게(그래도 마지막 묶음 하나는 늘) 최대 `INITIAL_FIT_MAX_BATCHES` 묶음의 화. 다음 묶음을 만들고 고치는 자리는
 * 대개 끝이고, 카드가 배율 1 근처에서 읽혀야 한다. 설정 노트는 넣지 않는다 — 노트는 1화 옆(맨 위)이라 함께 맞추면
 * 맞춤 상자가 처음부터 끝까지가 되어 화가 많을수록 카드가 읽히지 않는 배율로 열린다(40화에서 0.13). 화가 없으면
 * 노트만이다. */
export const INITIAL_FIT_MAX_BATCHES = 3;
export const INITIAL_FIT_MAX_EPISODES = 4;

export function toInitialFitNodeIds(nodes: readonly BoardNode[], model: BoardModel): { id: string }[] {
  const episodeCountByBatch = new Map<string, number>();
  for (const node of nodes) {
    if (node.type === "episode") {
      episodeCountByBatch.set(node.data.batchId, (episodeCountByBatch.get(node.data.batchId) ?? 0) + 1);
    }
  }
  const batchesFromEnd = [...model.batches]
    .filter((batch) => episodeCountByBatch.has(batch.id))
    .sort((a, b) => b.ordinal - a.ordinal);
  const fitBatchIds = new Set<string>();
  let episodeCount = 0;
  for (const batch of batchesFromEnd) {
    const count = episodeCountByBatch.get(batch.id) ?? 0;
    const isFull = fitBatchIds.size >= INITIAL_FIT_MAX_BATCHES || episodeCount + count > INITIAL_FIT_MAX_EPISODES;
    if (fitBatchIds.size > 0 && isFull) break;
    fitBatchIds.add(batch.id);
    episodeCount += count;
  }
  if (fitBatchIds.size === 0) return nodes.filter((node) => node.id === NOTES_NODE_KEY).map((node) => ({ id: node.id }));
  return nodes
    .filter((node) => node.type === "episode" && fitBatchIds.has(node.data.batchId))
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
