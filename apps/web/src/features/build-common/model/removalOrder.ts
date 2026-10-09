/**
 * 되돌릴 수 있게 잡아 둔 삭제 하나의 자리 정보 — 지운 항목의 id 와, 지울 때 그 목록의 id 순서(지운 항목 포함).
 *
 * `order` 에는 아직 되돌릴 수 있는 앞선 삭제도 제자리에 끼워 둔다. 그래야 연달아 지운 항목들을 어떤 차례로 되돌려도 서로의
 * 앞뒤가 지우기 전과 같아진다. 위치를 인덱스로만 기억하면 순서를 바꿔 되돌릴 때 어긋난다 — 예를 들어 `가 나 다 라` 에서
 * 나·다를 차례로 지운 뒤 나를 먼저 되돌리고 다를 되돌리면, 다가 지울 때의 인덱스(1)로 들어가 `가 다 나 라` 가 된다.
 */
export type RemovalPlace = { id: string; order: readonly string[] };

/**
 * `order` 에서 `id` 바로 앞에 있던 것들 가운데 지금 `ids` 에 남아 있는 가장 가까운 것 뒤가 `id` 의 자리다. 앞의 것이
 * 하나도 남아 있지 않으면 맨 앞이다. 그 사이 새로 추가한 항목은 원래 순서에 없으므로 기준이 되지 않고 제자리에 남는다.
 */
export function insertionIndex(ids: readonly string[], order: readonly string[], id: string): number {
  for (let at = order.indexOf(id) - 1; at >= 0; at--) {
    const found = ids.indexOf(order[at] ?? "");
    if (found !== -1) return found + 1;
  }
  return 0;
}

/**
 * 항목 하나를 지우기 직전의 `RemovalPlace.order` 를 만든다. `ids` 는 지금 목록(지울 항목 포함), `pending` 은 같은 목록에서
 * 앞서 지웠고 아직 되돌릴 수 있는 것들(지운 차례대로)이다 — 그것들을 각자 기억한 자리에 다시 끼운다.
 */
export function orderWithPendingRemovals(ids: readonly string[], pending: readonly RemovalPlace[]): string[] {
  const order = [...ids];
  for (const removed of pending) {
    if (order.includes(removed.id)) continue;
    order.splice(insertionIndex(order, removed.order, removed.id), 0, removed.id);
  }
  return order;
}

/**
 * 지운 항목을 다시 넣을 인덱스. 자리는 지울 때 바로 앞에 있던 항목 뒤다(그것도 지워졌으면 그 앞, 하나도 없으면 맨 앞).
 * 같은 id 가 이미 목록에 있으면(이미 되돌렸다) `undefined` 다 — 같은 id 가 둘이면 열림 키가 어느 쪽을 가리키는지 갈리지 않는다.
 */
export function restoreIndex(ids: readonly string[], removed: RemovalPlace): number | undefined {
  if (ids.includes(removed.id)) return undefined;
  return insertionIndex(ids, removed.order, removed.id);
}
