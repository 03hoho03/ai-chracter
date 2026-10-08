import { nodeKeyToSelection } from "./boardSelection";

// 라이브러리의 노드 변경 가운데 이 판정이 읽는 칸. 추가 변경처럼 id 가 없는 것도 섞여 온다.
type SelectionChangeLike = { type: string; id?: string; selected?: boolean };

/**
 * 라이브러리가 보낸 노드 변경 가운데 "이 카드를 골랐다"는 것. 고르기를 푸는 변경(`selected: false`)은 보지 않는다 —
 * 라이브러리는 끌기를 시작할 때(끌기만으로는 고르지 않게 해 두었다)도 다른 카드의 고르기를 풀어서, 그걸 따르면 카드를
 * 옮기려고 잡기만 해도 패널이 개요로 바뀐다. 고르기를 푸는 길은 빈 곳 클릭과 고른 카드에서의 Esc 둘뿐이다.
 * 고를 수 없는 노드(묶음 테두리)는 빼고, 고른 카드가 없으면 `undefined`.
 */
export function pickSelectedNodeKey(changes: readonly SelectionChangeLike[]): string | undefined {
  for (const change of changes) {
    if (change.type !== "select" || change.selected !== true || change.id === undefined) continue;
    if (nodeKeyToSelection(change.id) !== undefined) return change.id;
  }
  return undefined;
}

/**
 * 카드에 포커스가 있을 때 누른 Esc 의 뜻. 고른 카드면 고르기를 풀고, 포커스만 있는 카드면 아무것도 하지 않는다 —
 * 라이브러리 기본 동작은 고르지 않은 카드의 Esc 를 "고르기"로 처리해, 그대로 두면 Esc 가 오히려 카드를 고른다.
 */
export function toCardEscapeAction(focusedNodeKey: string, selectedNodeKey: string | undefined): "deselect" | "ignore" {
  return focusedNodeKey === selectedNodeKey ? "deselect" : "ignore";
}
