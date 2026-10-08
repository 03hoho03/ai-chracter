import {
  BATCH_FRAME_LABEL_HEIGHT,
  BATCH_FRAME_PADDING,
  EPISODE_NODE_HEIGHT,
  EPISODE_NODE_WIDTH,
  batchFrameNodeKey,
  type BatchFrameNode,
  type BoardModel,
  type BoardNode,
  type EpisodeNode,
} from "./boardNode";

type Bounds = { minX: number; minY: number; maxX: number; maxY: number };

/** 화 카드가 차지하는 상자. 화면에 그려진 뒤에는 잰 크기를, 그 전에는 카드의 정해진 크기를 쓴다. */
function episodeBounds(node: EpisodeNode): Bounds {
  const width = node.measured?.width ?? EPISODE_NODE_WIDTH;
  const height = node.measured?.height ?? EPISODE_NODE_HEIGHT;
  return { minX: node.position.x, minY: node.position.y, maxX: node.position.x + width, maxY: node.position.y + height };
}

function union(a: Bounds | undefined, b: Bounds): Bounds {
  if (!a) return b;
  return {
    minX: Math.min(a.minX, b.minX),
    minY: Math.min(a.minY, b.minY),
    maxX: Math.max(a.maxX, b.maxX),
    maxY: Math.max(a.maxY, b.maxY),
  };
}

/**
 * 묶음 테두리를 지금 화 카드 위치에 맞춰 다시 계산한다(첫 배치 때, 그리고 화를 옮긴 뒤마다).
 *
 * 테두리는 화 카드를 자식으로 품지 않는다(`parentId` 를 쓰지 않는다). 자식으로 묶으면 화 카드 위치가 테두리 기준
 * 상대값이 되어 저장된 좌표가 묶음 구성에 매이고, 테두리를 화에 맞춰 키우는 일도 따로 해야 한다. 대신 구성 화의 경계
 * 상자를 둘러싼, 끌거나 고를 수 없는 배경 노드로 두고 노드 배열 맨 앞에 놓는다 — 배열 순서가 그리는 순서라 화 카드
 * 뒤에 깔린다.
 * 화가 하나도 없는 묶음은 테두리를 그리지 않는다.
 */
export function fitBatchFrames(nodes: BoardNode[], model: BoardModel): BoardNode[] {
  const boundsByBatch = new Map<string, Bounds>();
  const rest: BoardNode[] = [];
  for (const node of nodes) {
    if (node.type === "batchFrame") continue;
    rest.push(node);
    if (node.type === "episode") {
      const { batchId } = node.data;
      boundsByBatch.set(batchId, union(boundsByBatch.get(batchId), episodeBounds(node)));
    }
  }

  const frames: BatchFrameNode[] = [...model.batches]
    .sort((a, b) => a.ordinal - b.ordinal)
    .flatMap((batch) => {
      const bounds = boundsByBatch.get(batch.id);
      if (!bounds) return [];
      const top = bounds.minY - BATCH_FRAME_PADDING - BATCH_FRAME_LABEL_HEIGHT;
      const left = bounds.minX - BATCH_FRAME_PADDING;
      const frame: BatchFrameNode = {
        id: batchFrameNodeKey(batch.id),
        type: "batchFrame",
        position: { x: left, y: top },
        width: bounds.maxX + BATCH_FRAME_PADDING - left,
        height: bounds.maxY + BATCH_FRAME_PADDING - top,
        data: { batchId: batch.id, ordinal: batch.ordinal, rangeLabel: batch.rangeLabel },
        draggable: false,
        selectable: false,
        focusable: false,
        connectable: false,
        deletable: false,
      };
      return [frame];
    });

  return [...frames, ...rest];
}
