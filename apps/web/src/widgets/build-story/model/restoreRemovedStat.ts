import type { StatDefValues } from "@/features/build-story";

/**
 * 되돌리기를 위해 잡아 둔 지운 스탯 — 값 그대로(같은 id)와, 어느 시작설정에서 어떤 순서 속에 있었는지.
 *
 * `order` 는 지울 때 그 시작설정의 스탯 id 순서다(지운 스탯 포함). 아직 되돌릴 수 있는 앞선 삭제도 제자리에 끼워 둔
 * 순서라, 연달아 지운 스탯들을 어떤 차례로 되돌려도 서로의 앞뒤가 지우기 전과 같아진다. 위치를 인덱스로만 기억하면 순서를
 * 바꿔 되돌릴 때 어긋난다 — 예를 들어 `가 나 다 라` 에서 나·다를 차례로 지운 뒤 나를 먼저 되돌리고 다를 되돌리면, 다가
 * 지울 때의 인덱스(1)로 들어가 `가 다 나 라` 가 된다.
 */
export type RemovedStat = {
  startingSetupId: string;
  order: readonly string[];
  stat: StatDefValues;
  /** 지우면서 우선순위 스탯을 '없음'으로 비운 엔딩의 id — 되돌릴 때 그 칸도 다시 이 스탯으로 채운다. */
  priorityEndingIds: readonly string[];
};

type StartingSetupStats = { id: string; stats: readonly StatDefValues[] };

/**
 * `order` 에서 `id` 바로 앞에 있던 것들 가운데 지금 `ids` 에 남아 있는 가장 가까운 것 뒤가 `id` 의 자리다. 앞의 것이
 * 하나도 남아 있지 않으면 맨 앞이다. 그 사이 새로 추가한 스탯은 원래 순서에 없으므로 기준이 되지 않고 제자리에 남는다.
 */
function insertionIndex(ids: readonly string[], order: readonly string[], id: string): number {
  for (let at = order.indexOf(id) - 1; at >= 0; at--) {
    const found = ids.indexOf(order[at] ?? "");
    if (found !== -1) return found + 1;
  }
  return 0;
}

/**
 * 스탯 하나를 지우기 직전의 `RemovedStat.order` 를 만든다. `ids` 는 지금 목록(지울 스탯 포함), `pending` 은 같은
 * 시작설정에서 앞서 지웠고 아직 되돌릴 수 있는 것들(지운 차례대로)이다 — 그것들을 각자 기억한 자리에 다시 끼운다.
 */
export function orderWithPendingRemovals(ids: readonly string[], pending: readonly RemovedStat[]): string[] {
  const order = [...ids];
  for (const removed of pending) {
    if (order.includes(removed.stat.id)) continue;
    order.splice(insertionIndex(order, removed.order, removed.stat.id), 0, removed.stat.id);
  }
  return order;
}

/**
 * 지운 스탯을 원래 시작설정의 원래 자리에 다시 넣은 목록을 돌려준다. 시작설정은 인덱스가 아니라 id 로 찾는다 — 그 사이
 * 시작설정 순서가 바뀌어도 제자리로 간다. 자리는 지울 때 바로 앞에 있던 스탯 뒤다(그 스탯도 지워졌으면 그 앞, 하나도
 * 없으면 맨 앞).
 *
 * 되돌릴 수 없으면 `undefined` 다: 시작설정이 사라졌거나, 같은 id 의 스탯이 이미 있을 때(이미 되돌렸다) — 같은 id 가
 * 둘이면 열림 키와 엔딩 조건이 어느 쪽을 가리키는지 갈리지 않는다.
 */
export function restoreRemovedStat(
  startingSetups: readonly StartingSetupStats[],
  removed: Pick<RemovedStat, "startingSetupId" | "order" | "stat">,
): { startingSetupIndex: number; stats: StatDefValues[] } | undefined {
  const startingSetupIndex = startingSetups.findIndex((setup) => setup.id === removed.startingSetupId);
  const setup = startingSetups[startingSetupIndex];
  if (setup === undefined) return undefined;
  const isDuplicate = startingSetups.some((each) => each.stats.some((stat) => stat.id === removed.stat.id));
  if (isDuplicate) return undefined;
  const index = insertionIndex(
    setup.stats.map((stat) => stat.id),
    removed.order,
    removed.stat.id,
  );
  return {
    startingSetupIndex,
    stats: [...setup.stats.slice(0, index), removed.stat, ...setup.stats.slice(index)],
  };
}

/**
 * 되살린 스탯을 다시 우선순위 스탯으로 채울 엔딩의 인덱스(되살린 시작설정의 엔딩 목록 기준). 지울 때 비운 엔딩을 id 로 찾고,
 * 그 사이 작가가 다른 스탯을 고른 엔딩은 덮지 않는다 — 여전히 '없음'인 엔딩만 채운다. 그 사이 지운 엔딩은 빠진다.
 */
export function endingsToRestorePriority(
  endings: readonly { id: string; priorityStatId: string | null }[],
  removed: Pick<RemovedStat, "priorityEndingIds">,
): number[] {
  return endings.flatMap((ending, index) =>
    ending.priorityStatId === null && removed.priorityEndingIds.includes(ending.id) ? [index] : [],
  );
}
