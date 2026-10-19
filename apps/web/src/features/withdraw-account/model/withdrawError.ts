import { formatAuthRateLimitMessage, getAuthRateLimit } from "@/entities/session";
import { isApiError } from "@/shared/api/client";

export const WITHDRAW_GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

/** 탈퇴 실패를 어디에 보일지. 비밀번호 오답은 고칠 칸이 있으니 칸 아래에(`field`), 나머지는 토스트로 보인다. */
export type WithdrawError = { target: "field"; message: string } | { target: "toast"; message: string };

/** 탈퇴 실패 → 표시. 비밀번호 오답 문구는 비밀번호 변경 폼과 같다(같은 서버 응답이다).
 *
 * 429 는 비밀번호 변경과 함께 쓰는 현재 비밀번호 확인 상한이다. 맞는 비밀번호여도 막히므로 오답 칸 오류가 아니라
 * 기다릴 시간을 말한다.
 *
 * 409 `WITHDRAWAL_CONFLICT` 는 탈퇴를 처리하는 사이 내 노벨에 새 구매가 들어와 서버가 아무것도 지우지 않고 돌려보낸
 * 것이다. 다시 누르면 그 구매까지 함께 처리되므로 다시 누르라고 말한다. */
export function getWithdrawError(error: unknown): WithdrawError {
  if (isApiError(error) && error.status === 400 && error.detail === "Current password is incorrect") {
    return { target: "field", message: "현재 비밀번호가 올바르지 않아요." };
  }
  if (isApiError(error) && error.status === 409 && detailCode(error.detail) === "WITHDRAWAL_CONFLICT") {
    return {
      target: "toast",
      message: "그사이 내 노벨에 새 구매가 생겨 탈퇴를 마치지 못했어요. 아무것도 지워지지 않았으니 다시 눌러 주세요.",
    };
  }
  const rateLimit = getAuthRateLimit(error);
  if (rateLimit) return { target: "toast", message: formatAuthRateLimitMessage(rateLimit, "password-confirm") };
  return { target: "toast", message: WITHDRAW_GENERIC_ERROR_MESSAGE };
}

function detailCode(detail: unknown): string | undefined {
  if (!detail || typeof detail !== "object" || !("code" in detail)) return undefined;
  const { code } = detail;
  return typeof code === "string" ? code : undefined;
}
