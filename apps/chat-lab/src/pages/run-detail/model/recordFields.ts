/**
 * 측정 서버가 원래 모양 그대로 넘기는 기록(드라이버 줄·덤프 줄·턴 기록 행·기억 스냅숏)에서 칸 하나를 읽는다. 이 기록들은 사람이
 * 고쳤거나 옛 판의 파일일 수 있어 칸의 타입을 믿지 않고, 모양이 다르면 undefined 로 본다.
 */
type LooseRecord = Readonly<Record<string, unknown>>;

export function readText(record: LooseRecord | null | undefined, key: string): string | undefined {
  const value = record?.[key];
  return typeof value === "string" ? value : undefined;
}

export function readNumber(record: LooseRecord | null | undefined, key: string): number | undefined {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function readBoolean(record: LooseRecord | null | undefined, key: string): boolean | undefined {
  const value = record?.[key];
  return typeof value === "boolean" ? value : undefined;
}

/** 칸이 객체 목록이면 객체인 원소만, 아니면 빈 목록. */
export function readRecords(record: LooseRecord | null | undefined, key: string): LooseRecord[] {
  const value = record?.[key];
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

export function readRecord(record: LooseRecord | null | undefined, key: string): LooseRecord | undefined {
  const value = record?.[key];
  return isRecord(value) ? value : undefined;
}

/** 칸이 있는가(값이 null 이어도) — 원문을 빼고 내보낸 기록은 칸째 없다. */
export function hasField(record: LooseRecord | null | undefined, key: string): boolean {
  return record != null && Object.hasOwn(record, key);
}

function isRecord(value: unknown): value is LooseRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
