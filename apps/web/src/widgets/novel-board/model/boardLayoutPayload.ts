import type { BoardNode, BoardPosition, BoardViewport, SavedBoardLayout } from "./boardNode";

/** 보드 배치 저장 요청 본문의 상한(JSON 길이). 노드 키가 ASCII 라 길이가 곧 바이트 수다. 화 100개·인물 수십 명이면
 * 10KB 안팎이라 이 상한에 닿는 것은 비정상적인 입력뿐이다 — 서버도 크기를 검사하므로 넘는 본문은 보내지 않는다. */
export const MAX_BOARD_LAYOUT_BYTES = 64 * 1024;

/** 저장 대상 노드인지. 묶음 테두리는 화 위치에서 다시 계산하는 파생 노드라 저장하지 않는다. */
function isPersistedNode(node: BoardNode): boolean {
  return node.type !== "batchFrame";
}

/** 좌표를 정수로 — 끌기가 남기는 소수점 아래 자리는 화면에서 구별되지 않고 본문만 키운다. */
function roundPosition(position: BoardPosition): BoardPosition {
  return { x: Math.round(position.x), y: Math.round(position.y) };
}

/**
 * 지금 보드의 노드 위치로 배치 저장 본문을 만든다. 본문은 지금 보드에 있는 노드의 키만 담는다 — 서버의 저장값은
 * 통째로 바뀌므로, 합치거나 지워져 사라진 인물·화의 옛 키는 다음 저장 때 이렇게 저절로 빠진다.
 * 본문이 상한을 넘으면 `null` 을 돌려주고, 호출부는 저장을 건너뛴다.
 */
export function buildBoardLayoutPayload(
  nodes: readonly BoardNode[],
  viewport: BoardViewport | undefined,
): SavedBoardLayout | null {
  const positions: Record<string, BoardPosition> = {};
  for (const node of nodes) {
    if (isPersistedNode(node)) positions[node.id] = roundPosition(node.position);
  }
  const payload: SavedBoardLayout = viewport ? { version: 1, positions, viewport } : { version: 1, positions };
  return JSON.stringify(payload).length > MAX_BOARD_LAYOUT_BYTES ? null : payload;
}
