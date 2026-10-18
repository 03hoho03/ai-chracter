import type { StatDef } from "./chatRoomState";

/** statId → 이번 턴에 움직인 양. 움직이지 않은 스탯은 키가 없다. */
export type StatDeltas = Record<string, number>;

/** 한 턴이 확정된 뒤 상태 줄이 알릴 것. `turn` 은 턴마다 새 값이라 같은 증감이 두 턴 연달아 와도 칩 타이머와 스크린리더
 * 안내가 다시 선다. 숨긴 스탯은 이름·값 없이 "바뀌었다"는 표시 하나만 온다. */
export type StatTurnFeedback = {
  turn: number;
  deltas: StatDeltas;
  hiddenSignal: boolean;
};

/** 숨긴 스탯이 바뀐 턴의 익명 신호 문구. 화면 글자와 스크린리더 안내가 같은 말을 쓴다. */
export const HIDDEN_STAT_SIGNAL_TEXT = "무언가 달라졌다";

/** `statChange` 하나를 이번 턴 증감에 더한다. 직전 값은 클라이언트 캐시의 값이라, 캐시에 그 스탯이 없으면(재접속·새로고침
 * 뒤 처음 받는 값) 증감을 알 수 없어 적지 않는다. 합이 0 이면 키를 지운다 — 칩에 "+0" 이 서지 않는다. */
export function addStatDelta(deltas: StatDeltas, statId: string, previous: number | undefined, next: number): StatDeltas {
  if (previous === undefined) return deltas;
  const total = (deltas[statId] ?? 0) + (next - previous);
  const updated = { ...deltas };
  if (total === 0) delete updated[statId];
  else updated[statId] = total;
  return updated;
}

/** 칩 글자. 방향은 기호가 진다 — 색으로 가르면 색각 이상 사용자에게 방향이 사라지고, 오르내림에 쓸 색도 이 시스템에 없다.
 * 마이너스는 하이픈이 아니라 수학 기호(U+2212)라 숫자와 폭이 맞는다. */
export function formatStatDelta(delta: number): string {
  return delta > 0 ? `+${delta}` : `−${Math.abs(delta)}`;
}

/** 게이지 값 표기를 강조할 숫자와 나머지로 나눈다. 퍼센트 단위는 "62%" 처럼 최대 없이 쓰고, 그 밖은 "48/100명" 이다.
 * `short` 는 최대를 접는다 — 증감 칩이 떠 있는 동안 그 자리를 칩에 내줘 이름 칸이 좁아지지 않게 한다. */
export function formatStatValue(
  stat: Pick<StatDef, "max" | "unit">,
  value: number,
  { short = false }: { short?: boolean } = {},
): { value: string; rest: string } {
  const unit = stat.unit ?? "";
  if (unit === "%" || short) return { value: String(value), rest: unit };
  return { value: String(value), rest: `/${stat.max}${unit}` };
}

/** 한 턴의 변화를 스크린리더가 한 번에 읽을 문장. 보이는 스탯 증감을 정의 순서대로("호감도 3 올라 48"), 그 뒤에 익명
 * 신호를 잇는다. 바뀐 것이 없으면 빈 글이다. */
export function buildStatTurnAnnouncement(
  stats: StatDef[],
  values: Record<string, number>,
  feedback: Pick<StatTurnFeedback, "deltas" | "hiddenSignal">,
): string {
  const sentences = stats.flatMap((stat) => {
    const delta = feedback.deltas[stat.id];
    if (delta === undefined) return [];
    const value = values[stat.id] ?? stat.initial;
    return [`${stat.name} ${Math.abs(delta)} ${delta > 0 ? "올라" : "내려"} ${value}${stat.unit ?? ""}`];
  });
  if (feedback.hiddenSignal) sentences.push(HIDDEN_STAT_SIGNAL_TEXT);
  return sentences.join(". ");
}
