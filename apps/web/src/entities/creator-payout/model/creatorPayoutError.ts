import { isApiError } from "@/shared/api/client";

function errorCode(error: unknown): unknown {
  if (!isApiError(error) || !error.detail || typeof error.detail !== "object") return undefined;
  return error.detail.code;
}

/** 정산 스위치가 꺼져 있다는 503. 스위치가 꺼지면 진입점(프로필 메뉴)이 숨으므로 이 응답은 화면을 열어 둔 채 꺼지는
 * 경합이나 직접 친 주소에서만 온다. 다시 시도해도 풀리지 않으므로 재시도하지 않는다. */
export function isCreatorPayoutUnavailableError(error: unknown): boolean {
  return isApiError(error) && error.status === 503 && errorCode(error) === "CREATOR_PAYOUT_UNAVAILABLE";
}

/** 정산 내역 "더 보기"에 쓴 cursor 를 서버가 읽지 못했다는 422. 같은 cursor 로 다시 물어도 같으므로 화면은 내역을
 * 처음부터 다시 읽는다. */
export function isCreatorPayoutCursorInvalidError(error: unknown): boolean {
  return isApiError(error) && error.status === 422 && errorCode(error) === "CREATOR_PAYOUT_CURSOR_INVALID";
}
