/** 원고 모델 하나의 이름과 원고 하나에 쓸 수 있는 턴(모델 응답) 수 상한 — 구성안 조회의 `chapterTurnCaps`, 장면 구성안 조회의
 * `chapterModels` 항목이 이 꼴을 갖는다. */
export type ChapterTurnCap = { name: string; maxTurns: number };

/** 상한이 같은 모델들. */
export type TurnCapGroup = { names: string[]; maxTurns: number };

/** 화 턴 수가 이 계정의 원고 모델 상한에 맞는가 — 모두 맞음, 일부만 넘음(쓸 수 있는 모델과 넘는 모델을 상한별로), 모두 넘음(가장 큰
 * 상한). */
export type TurnCapFit =
  | { kind: "fits" }
  | { kind: "some"; ableNames: string[]; over: TurnCapGroup[] }
  | { kind: "none"; maxTurns: number };

/** 화 턴 수를 원고 모델 상한과 견준다. 서버처럼 상한을 **넘을 때만** 못 쓴다(상한과 같으면 쓴다). 턴 수를 모르거나(셀 수 없는 화) 상한
 * 목록이 비었으면(그 칸을 싣기 전 서버) 판정하지 않는다. */
export function toTurnCapFit(turnCount: number | null | undefined, caps: readonly ChapterTurnCap[]): TurnCapFit | undefined {
  if (turnCount === null || turnCount === undefined || caps.length === 0) return undefined;
  const over = caps.filter((cap) => cap.maxTurns < turnCount);
  if (over.length === 0) return { kind: "fits" };
  if (over.length === caps.length) return { kind: "none", maxTurns: Math.max(...caps.map((cap) => cap.maxTurns)) };
  const limits = [...new Set(over.map((cap) => cap.maxTurns))].sort((a, b) => a - b);
  return {
    kind: "some",
    ableNames: caps.filter((cap) => cap.maxTurns >= turnCount).map((cap) => cap.name),
    over: limits.map((maxTurns) => ({
      names: over.filter((cap) => cap.maxTurns === maxTurns).map((cap) => cap.name),
      maxTurns,
    })),
  };
}

/** 넘는 모델의 상한 한 구절 — "Sonnet 5.5·Opus 5.5 는 20턴까지", 상한이 다르면 "Sonnet 5.5 는 20턴, Opus 5.5 는 30턴까지". */
export function toOverCapPhrase(over: readonly TurnCapGroup[]): string {
  return `${over.map((group) => `${group.names.join("·")} 는 ${group.maxTurns.toLocaleString()}턴`).join(", ")}까지`;
}
