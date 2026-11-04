import type { StatSeries } from "@/shared/api/client";

/** 한 차트에 긋는 선의 상한 — 스탯 선 색이 셋이라 넷째 색을 지어내지 않는다. 넷 이상이면 보일 셋을 고른다. */
export const MAX_LINES = 3;

/** 선을 그을 수 있는 계열 — 드라이버에서 온 보이는 스탯. 숨김 스탯과 턴 기록에서만 온 스탯은 본 차트 아래 따로 그린다. */
export function lineCandidates(series: ReadonlyArray<StatSeries>): StatSeries[] {
  return series.filter((entry) => entry.source === "driver" && entry.hidden !== true);
}

/**
 * 기본 선 자리 — 선 후보의 앞 셋(계열 순서). 자리 k 가 선 색 k 다. 색이 자리를 따르므로, 스탯을 고르지 않으면 같은 스탯이 늘 같은
 * 색이다.
 */
export function defaultSlots(series: ReadonlyArray<StatSeries>): string[] {
  return lineCandidates(series)
    .slice(0, MAX_LINES)
    .map((entry) => entry.id);
}

/**
 * 자리 하나에 스탯을 고른다. 그 스탯이 이미 다른 자리에 있으면 두 자리를 맞바꾼다 — 한 스탯이 두 선으로 서지 않고, 고르지 않은
 * 자리의 스탯은 제 색을 지킨다.
 */
export function pickSlot(slots: ReadonlyArray<string>, slot: number, id: string): string[] {
  const current = slots[slot];
  if (current === undefined) return [...slots];
  return slots.map((entry, index) => {
    if (index === slot) return id;
    return entry === id ? current : entry;
  });
}

/** 화면이 들고 있는 고른 자리를 이 런에 맞춘다. 이 런의 선 후보에 없는 스탯이 있거나 자리 수가 다르면 기본 자리다. */
export function resolveSlots(series: ReadonlyArray<StatSeries>, picked: ReadonlyArray<string> | undefined): string[] {
  const fallback = defaultSlots(series);
  if (picked === undefined || picked.length !== fallback.length) return fallback;
  const known = new Set(lineCandidates(series).map((entry) => entry.id));
  return picked.every((id) => known.has(id)) ? [...picked] : fallback;
}
