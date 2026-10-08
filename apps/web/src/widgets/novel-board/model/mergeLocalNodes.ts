import type { BoardModel, BoardNode } from "./boardNode";
import { fitBatchFrames } from "./fitBatchFrames";

/**
 * 서버 데이터가 다시 와서 노드를 새로 계산했을 때, 지금 화면의 노드 자리와 잰 크기를 그대로 잇는다.
 *
 * 화면의 자리가 이긴다 — 카드를 옮긴 뒤 저장(1초 디바운스)이 나가기 전에 상세를 다시 받으면(제목 고치기, 묶음 하나가
 * 끝난 연쇄 생성) 새 계산은 아직 저장 전 자리를 몰라 카드를 옮기기 전 자리로 되돌린다. 처음 그릴 때는 이미 받은
 * 배치로 계산하므로, 그 뒤 새 계산과 화면이 갈리는 것은 이 화면이 옮긴 카드뿐이다. 잰 크기를 잇지 않으면 라이브러리가
 * 크기를 다시 잴 때까지 카드를 숨긴다.
 *
 * 새로 생긴 노드(새 화·새 인물)는 계산한 자리 그대로다. 사라진 노드는 따라오지 않는다. 묶음 테두리는 이은 자리로
 * 다시 둘러싸고, 바뀌지 않은 테두리는 화면의 객체를 그대로 쓴다(`fitBatchFrames`).
 */
export function mergeLocalNodes(next: readonly BoardNode[], current: readonly BoardNode[], model: BoardModel): BoardNode[] {
  const currentById = new Map(current.map((node) => [node.id, node]));
  const merged = next.map((node): BoardNode => {
    const local = currentById.get(node.id);
    if (local === undefined) return node;
    // 테두리는 아래에서 다시 둘러싸며, 자리·크기가 같으면 화면의 객체(잰 크기 포함)를 그대로 쓴다.
    if (node.type === "batchFrame" || local.type === "batchFrame") return local;
    return { ...node, position: local.position, measured: local.measured };
  });
  return fitBatchFrames(merged, model);
}
