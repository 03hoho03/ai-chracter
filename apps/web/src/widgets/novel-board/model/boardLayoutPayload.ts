import type { NovelBoardLayout, NovelBoardViewport } from "@/entities/novel";

import type { BoardNode, BoardPosition } from "./boardNode";

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
 *
 * `viewport` 는 화면 위치를 모르면 `null` 로 **늘 싣는다** — 서버 칸에 기본값이 없어 키가 빠지면 422 다.
 *
 * 본문이 `maxBytes`(상세 `limits.boardLayoutMaxBytes`)를 넘으면 `null` 을 돌려주고 호출부는 저장을 건너뛴다. 노드 키가
 * ASCII 라 JSON 길이가 곧 바이트 수다. 서버는 좌표를 실수로 다시 직렬화해(`12` → `12.0`) 같은 본문을 조금 더 크게
 * 재므로 이 검사를 통과하고도 서버가 422 를 줄 수 있다 — 화 수백 개여도 상한에 한참 못 미쳐 실사용에서 닿지 않고, 닿으면
 * 저장 쪽이 그 422 를 조용히 건너뛴다.
 */
export function buildBoardLayoutPayload(
  nodes: readonly BoardNode[],
  viewport: NovelBoardViewport | null,
  maxBytes: number,
): NovelBoardLayout | null {
  const positions: Record<string, BoardPosition> = {};
  for (const node of nodes) {
    if (isPersistedNode(node)) positions[node.id] = roundPosition(node.position);
  }
  const payload: NovelBoardLayout = { version: 1, positions, viewport };
  return JSON.stringify(payload).length > maxBytes ? null : payload;
}
