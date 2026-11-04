import type { RunListItem } from "./client";

/**
 * 턴 기록에서 오는 칸(원가·토큰·기억·라우팅)이 런 전체에서 비는 까닭. 측정 서버가 준 형식과 턴 기록 파일 유무만 본다.
 * - `oldFormat`: `assistantMessageId` 이전 형식 — 턴 기록 행을 응답과 이을 열쇠가 없어 측정 서버가 행을 잇지 않고 내보내기도
 *   거부한다. 파일이 있어도 비고, 내보내라고 하면 안 된다.
 * - `needsExport`: 턴 기록 파일이 없다 — 내보내면 채워진다.
 *
 * 현행 형식에 파일이 있으면 undefined — 그때 칸이 비는 까닭은 그 시도에 붙은 행이 없는 것이다.
 */
export type RecordGap = "oldFormat" | "needsExport";

export function runRecordGap(run: Pick<RunListItem, "format" | "hasChatTurns">): RecordGap | undefined {
  if (run.format === "preMessageId") return "oldFormat";
  return run.hasChatTurns ? undefined : "needsExport";
}

/** 원가 자리에 적는 낱말 — 그 자리 앞에 "원가"가 이미 붙어 있다(표 머리·필드 이름·"이 턴 원가"). */
export const COST_GAP_TEXT = {
  oldFormat: "없음 · 이전 형식",
  needsExport: "내보내기 필요",
} as const satisfies Record<RecordGap, string>;

/** 원가 밖의 턴 기록 칸(토큰·기억·라우팅)에 적는 낱말. */
export const RECORD_GAP_TEXT = {
  oldFormat: "이전 형식이라 턴 기록을 잇지 않음",
  needsExport: "내보내기 필요",
} as const satisfies Record<RecordGap, string>;

/** 이전 형식 런을 내보낼 수 없는 까닭 — 측정 서버가 그 런의 내보내기를 거부하는 까닭(`unsupportedFormat`)과 같다. */
export const OLD_FORMAT_EXPORT_REASON = "이 형식은 턴 기록을 응답과 이을 열쇠(응답 id)가 없어 내보내도 이을 수 없다";
