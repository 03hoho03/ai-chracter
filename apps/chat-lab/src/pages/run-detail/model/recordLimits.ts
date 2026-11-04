import type { RecordLimit } from "@/shared/api/client";

/**
 * 측정 서버가 이 턴에 준 기록 한계 문장 가운데 그 자리(`slot`)에 설 문장. 없으면 undefined — 그 자리는 값이 있거나, 이 턴에는
 * 해당하지 않는다. 문장은 고치지 않고 그대로 쓴다.
 */
export function recordLimitText(limits: ReadonlyArray<RecordLimit>, slot: RecordLimit["slot"]): string | undefined {
  return limits.find((limit) => limit.slot === slot)?.text;
}
