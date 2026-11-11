/** 배열이 아닌 객체인가 — 실행 중에 받은 JSON 의 겉모양을 볼 때 칸을 읽기 전에 거친다. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
