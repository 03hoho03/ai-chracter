import { isApiError } from "@/shared/api/client";

// 서버가 칸 자리 경합에 돌려주는 409 의 `detail.code`. 응답에 실리는 실제 식별자다.
const POSITION_TAKEN_CODE = "MEDIA_BOOK_CELL_POSITION_TAKEN";

/**
 * 다른 창(또는 기기)이 같은 인물 × 장면 자리에 먼저 새 칸을 저장해, 이 화면의 저장이 거절된 경우의 안내. 이 화면의
 * 폼에는 여전히 그 자리의 다른 칸이 들어 있어 기다려도 풀리지 않는다 — 새로고침해 저장된 쪽을 불러와야 한다.
 */
export const MEDIA_BOOK_POSITION_TAKEN_MESSAGE =
  "다른 창에서 같은 미디어 북 칸에 먼저 그림을 넣어 저장이 멈췄어요. 새로고침하면 저장된 내용을 불러와요(이 창에서 그 뒤에 고친 내용은 사라져요).";

export function isMediaBookPositionTakenError(error: unknown): boolean {
  if (!isApiError(error) || error.status !== 409) return false;
  return typeof error.detail === "object" && error.detail.code === POSITION_TAKEN_CODE;
}

/** 자동저장 실패 토스트 문구. 미디어 북 자리 경합이 아니면 undefined(기본 문구). */
export function storyAutosaveErrorMessage(error: unknown): string | undefined {
  return isMediaBookPositionTakenError(error) ? MEDIA_BOOK_POSITION_TAKEN_MESSAGE : undefined;
}
