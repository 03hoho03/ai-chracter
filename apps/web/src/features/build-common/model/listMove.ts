/** 순서 있는 목록에서 항목 하나를 옮기는 한 번의 이동(`useFieldArray` 의 `move(from, to)` 인자). 배열 위치가 곧 순서다. */
export type MoveIndices = { from: number; to: number };

/** 끌어 온 항목(`activeId`)을 놓은 자리의 항목(`overId`) 위치로 옮긴다. 제자리·목록 밖·모르는 id 면 undefined. */
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

/** 키보드로 한 칸 옮기는 이동과, 옮긴 항목의 id. */
export type StepMove = MoveIndices & { movedId: string };

/**
 * 손잡이에서 화살표 키로 `index` 의 항목을 한 칸 위(-1)나 아래(1)로 옮긴다. 양 끝을 넘거나 모르는 자리면 undefined.
 *
 * 포커스는 옮긴 항목을 따라가야 한다 — 이동 전 `index` 에 있던 항목(`movedId`)이고, 이동 뒤 그 자리로 밀려온 이웃이 아니다.
 * 그래야 손잡이에서 화살표를 거듭 누르면 같은 항목이 계속 움직이고, "N번째로 옮겼어요" 안내가 포커스가 있는 항목을 말한다.
 */
export function stepMove(ids: readonly string[], index: number, step: -1 | 1): StepMove | undefined {
  const to = index + step;
  const movedId = ids[index];
  if (movedId === undefined || to < 0 || to >= ids.length) return undefined;
  return { from: index, to, movedId };
}

/** `ids` 에 이동 하나를 적용한 뒤의 순서(옮긴 뒤의 자리를 안내 문장에 쓴다). */
export function orderAfterMove(ids: readonly string[], { from, to }: MoveIndices): string[] {
  const next = [...ids];
  const [moved] = next.splice(from, 1);
  if (moved !== undefined) next.splice(to, 0, moved);
  return next;
}

/**
 * 화면 읽기 안내 영역에 넣을 다음 값. 같은 문장이 연달아 오면(같은 칸으로 다시 옮기기, 연달아 지우기) 영역의 글자가 바뀌지
 * 않아 다시 읽히지 않으므로, 그때는 끝에 줄바꿈 없는 공백을 붙여 값을 바꾼다 — 읽는 소리는 같다.
 */
export function nextAnnouncement(previous: string, message: string): string {
  return previous === message ? `${message} ` : message;
}
