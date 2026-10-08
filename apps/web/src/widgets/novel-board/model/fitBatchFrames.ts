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

const BATCH_FRAME_DOM_ATTRIBUTES = { "aria-hidden": true, "aria-roledescription": undefined };

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
 *
 * 입력에 같은 자리·크기·머리 줄의 테두리가 이미 있으면 그 객체를 그대로 돌려준다. 라이브러리는 노드 객체가 바뀌면
 * 그 노드를 다시 재는데, 다시 계산할 때마다 새 테두리를 주면 잰 크기가 사라져 재기 → 다시 계산 → 재기가 끝없이 돈다.
 */
export function fitBatchFrames(nodes: BoardNode[], model: BoardModel): BoardNode[] {
  const boundsByBatch = new Map<string, Bounds>();
  const existingFrames = new Map<string, BatchFrameNode>();
  const rest: BoardNode[] = [];
  for (const node of nodes) {
    if (node.type === "batchFrame") {
      existingFrames.set(node.id, node);
      continue;
    }
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
        // 장식이라 읽히지 않게 숨긴다 — 라이브러리가 모든 노드 상자에 다는 영어 역할 설명("node")도 지운다.
        domAttributes: BATCH_FRAME_DOM_ATTRIBUTES,
      };
      const existing = existingFrames.get(frame.id);
      return [existing !== undefined && isSameFrame(existing, frame) ? existing : frame];
    });

  return [...frames, ...rest];
}

function isSameFrame(a: BatchFrameNode, b: BatchFrameNode): boolean {
  return (
    a.position.x === b.position.x &&
    a.position.y === b.position.y &&
    a.width === b.width &&
    a.height === b.height &&
    a.data.ordinal === b.data.ordinal &&
    a.data.rangeLabel === b.data.rangeLabel
  );
}
