/**
 * 턴당 자동 변화 입력칸의 값을 폼 값으로 바꾼다. 빈 칸에 `valueAsNumber` 를 쓰면 NaN 이 들어가 zod 가 막으므로 빈 칸은
 * 직접 null 로 되돌린다(undefined 가 아닌 이유는 스토리 빌더 스키마의 `perTurnDelta` 주석).
 */
export function perTurnDeltaFromInput(value: unknown): number | null {
  return value === "" || value === null ? null : Number(value);
}
