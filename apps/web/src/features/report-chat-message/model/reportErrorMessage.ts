import { z } from "zod";

import { isApiError } from "@/shared/api/client";

/** 신고 레이트리밋 429 의 `detail.code`. OpenAPI 에 실리지 않는 값이라 코드젠 타입이 없다. */
export const CHAT_REPORT_RATE_LIMITED = "CHAT_REPORT_RATE_LIMITED";

// 공용 `shared/api/rateLimit.ts` 파서를 쓰지 않는 이유: 그 파서는 `code`·`window` 를 닫힌 목록으로
// 검사하는데, 신고 429 는 댓글 신고와 같은 모양(`code`·`message`·`retryAfterSeconds`·`windowSeconds`)이라
// 그 목록 밖이다. 거기에 넣으면 이 응답이 `null` 로 떨어져 일반 실패 문구가 뜬다. 그래서 이 기능 안에서
// 필요한 두 칸만 느슨하게 읽는다.
const detailSchema = z.object({
  code: z.string().optional(),
  retryAfterSeconds: z.number().nonnegative().optional(),
});

export function reportErrorMessage(error: unknown): string {
  if (!isApiError(error)) return "신고 접수에 실패했어요. 잠시 후 다시 시도해주세요.";
  const parsed = detailSchema.safeParse(error.detail);
  const detail = parsed.success ? parsed.data : undefined;

  if (error.status === 401) return "로그인이 만료됐어요. 다시 로그인한 뒤 신고해주세요.";
  if (detail?.code === CHAT_REPORT_RATE_LIMITED) {
    const seconds = detail.retryAfterSeconds;
    return seconds ? `${seconds}초 후 다시 신고할 수 있어요. 고른 사유는 그대로 남아 있어요.` : "신고를 너무 빠르게 보냈어요. 잠시 후 다시 시도해주세요.";
  }
  if (error.status === 404) return "이 응답을 찾을 수 없어요. 다시 생성됐거나 삭제됐을 수 있어요.";
  if (error.status === 403) return "현재 계정 상태에서는 신고할 수 없어요.";
  return "신고 접수에 실패했어요. 잠시 후 다시 시도해주세요.";
}
