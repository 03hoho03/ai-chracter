import { z } from "zod";

import { isApiError } from "@/shared/lib/api/client";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

/** BE `admin/router.py` 로그인이 내는 429 detail. 이 계약은 OpenAPI 에 실리지 않아 서버가 주는 외부 데이터로
 * 보고 스키마로 파싱한다 — 모양이 다르면 일반 오류로 떨어진다. */
const authLimitDetailSchema = z.object({
  code: z.literal("AUTH_LIMIT"),
  retryAfterSeconds: z.number(),
  window: z.literal("auth"),
});

/** 관리자 로그인 제출 실패 → 배너 문구. 429 는 맞는 비밀번호여도 상한을 넘으면 나므로 기다릴 분을 말한다.
 * 분은 올림이다 — 내림이면 그 시각에 다시 눌러도 막힌다. 문구는 web 로그인 폼과 같다. */
export function getLoginErrorMessage(error: unknown): string {
  const apiError = isApiError(error) ? error : undefined;
  if (apiError?.status === 401) return "이메일 또는 비밀번호가 올바르지 않습니다.";
  if (apiError?.status === 429) {
    const parsed = authLimitDetailSchema.safeParse(apiError.detail);
    if (parsed.success) {
      const minutes = Math.max(1, Math.ceil(parsed.data.retryAfterSeconds / 60));
      return `로그인 시도가 너무 많았어요 · 약 ${minutes}분 뒤에 다시 시도할 수 있어요`;
    }
  }
  return GENERIC_ERROR_MESSAGE;
}
