import type { AttemptDetail, TurnDetail } from "@/shared/api/client";
import { assertNever } from "@/shared/lib/assertNever";

import { hasField, readText } from "./recordFields";
import { recordLimitText } from "./recordLimits";
import type { DumpSource } from "./runDetailSearch";

type LooseRecord = Readonly<Record<string, unknown>>;

/**
 * 원문 칸에 무엇을 보일지. 원문이 없을 때 "왜 없는지"가 갈래마다 달라 따로 둔다 — 빈 칸 하나로 덮으면 덤프가 없는 묶음과 원문을
 * 빼고 내보낸 묶음과 고르지 않은 시도가 구별되지 않는다.
 * - `noDumpFile`: 이 묶음에 짝인 프롬프트 덤프가 없다 — 측정 서버의 기록 한계 문장(`text`)을 그대로 보인다.
 * - `notSelectedAttempt`: 생성 덤프는 DB 응답으로 고른 시도에만 붙는다.
 * - `noDumpForAttempt`: 고른 시도인데 붙은 생성 덤프가 없다(불일치 목록에 덤프 없는 턴으로 있다).
 * - `excluded`: 덤프 줄은 있지만 원문 칸을 빼고 만든 기록이다.
 * - `emptyPrompt`: 프롬프트 칸은 있는데 글이 아니다(null 등) — 원문을 뺀 기록과 달리 칸째 빠지지 않았다.
 * - `noField`: 이 덤프 줄에는 지시문이 없다 — 그 호출이 지시문을 따로 보내지 않았다.
 */
export type RawView =
  | { kind: "text"; text: string }
  | { kind: "noDumpFile"; text: string }
  | { kind: "notSelectedAttempt"; earlierCount: number }
  | { kind: "noDumpForAttempt" }
  | { kind: "excluded" }
  | { kind: "emptyPrompt" }
  | { kind: "noField" };

export type RawField = "prompt" | "systemInstruction";

/** 원문 출처가 가리키는 덤프 줄. 없으면 undefined. */
export function pickDumpRecord(
  turnDetail: TurnDetail,
  attempt: AttemptDetail | undefined,
  source: DumpSource,
): LooseRecord | undefined {
  switch (source.kind) {
    case "generation":
      return attempt?.generationDump ?? undefined;
    case "earlier":
      return turnDetail.earlierGenerationDumps[source.index - 1];
    case "judgment":
      return turnDetail.judgmentDumps[source.index - 1];
    case "background":
      return turnDetail.backgroundDumps[source.index - 1]?.record;
    default:
      return assertNever(source);
  }
}

export function describeRaw(
  turnDetail: TurnDetail,
  attempt: AttemptDetail | undefined,
  source: DumpSource,
  field: RawField,
): RawView {
  const record = pickDumpRecord(turnDetail, attempt, source);
  if (record === undefined) {
    // 덤프 파일이 없는 묶음이면 측정 서버가 원문 자리에 설 문장을 준다.
    const noDumpText = recordLimitText(turnDetail.recordLimits, "promptDump");
    if (noDumpText !== undefined) return { kind: "noDumpFile", text: noDumpText };
    if (source.kind === "generation" && attempt !== undefined && !attempt.selected) {
      return { kind: "notSelectedAttempt", earlierCount: turnDetail.earlierGenerationDumps.length };
    }
    return { kind: "noDumpForAttempt" };
  }
  const text = readText(record, field);
  if (text !== undefined) return { kind: "text", text };
  // 원문을 빼고 만든 기록은 프롬프트 칸째 없다. 프롬프트 칸이 있는데 글이 아니면, 프롬프트를 물었을 때는 그 칸이 빈 것이고
  // 지시문을 물었을 때는 그 호출이 지시문을 따로 보내지 않은 것이다.
  if (!hasField(record, "prompt")) return { kind: "excluded" };
  return field === "prompt" ? { kind: "emptyPrompt" } : { kind: "noField" };
}

/** 출처 고르기에 적을 이름. */
export function dumpSourceLabel(turnDetail: TurnDetail, attempt: AttemptDetail | undefined, source: DumpSource): string {
  switch (source.kind) {
    case "generation":
      return `생성 · 시도 ${attempt?.index ?? "-"}`;
    case "earlier":
      return `앞선 생성 덤프 ${source.index}`;
    case "judgment":
      return `판정 · ${readText(turnDetail.judgmentDumps[source.index - 1], "callSite") ?? "call_site 없음"}`;
    case "background":
      return `백그라운드 · ${readText(turnDetail.backgroundDumps[source.index - 1]?.record, "callSite") ?? "call_site 없음"}`;
    default:
      return assertNever(source);
  }
}

/** 이 턴에서 원문 칸이 고를 수 있는 출처 전부 — 생성, 앞선 생성 덤프, 판정, 백그라운드 순. */
export function dumpSources(turnDetail: TurnDetail): DumpSource[] {
  return [
    { kind: "generation" },
    ...turnDetail.earlierGenerationDumps.map((_, index) => ({ kind: "earlier" as const, index: index + 1 })),
    ...turnDetail.judgmentDumps.map((_, index) => ({ kind: "judgment" as const, index: index + 1 })),
    ...turnDetail.backgroundDumps.map((_, index) => ({ kind: "background" as const, index: index + 1 })),
  ];
}
