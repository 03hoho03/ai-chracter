/** 노트 순서를 바꾸는 한 번의 이동(`useFieldArray` 의 `move(from, to)` 인자). 배열 위치가 곧 우선순위다. */
export type MoveIndices = { from: number; to: number };

/** 드래그한 노트(`activeId`)를 놓은 자리의 노트(`overId`) 위치로 옮긴다. 제자리·목록 밖·모르는 id 면 undefined. */
export function dragMoveIndices(
  ids: readonly string[],
  activeId: string,
  overId: string | null,
): MoveIndices | undefined {
  if (overId === null || activeId === overId) return undefined;
  const from = ids.indexOf(activeId);
  const to = ids.indexOf(overId);
  return from === -1 || to === -1 ? undefined : { from, to };
}

/** 키보드 재정렬 — 한 칸 위(-1)나 아래(1)로. 양 끝을 넘으면 undefined. */
export function stepMoveIndices(index: number, step: -1 | 1, length: number): MoveIndices | undefined {
  const to = index + step;
  return to < 0 || to >= length ? undefined : { from: index, to };
}
