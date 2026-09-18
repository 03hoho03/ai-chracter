import { z } from "zod";

import { isApiError } from "./client";

/** limit-goal-prompt.md RL-11, error-delivery-goal-prompt.md ED-15 — BE `core/rate_limit_gate.py`와
 * `auth/router.py`가 내는 429 바디 `{"detail": {"code", "retryAfterSeconds", "window"}}`.
 * `Retry-After` 헤더는 일부러 주지 않으므로(CORS에서 못 읽는다) 재시도 시점의 유일한 출처가 이 detail이다.
 *
 * 단언 대신 스키마로 파싱하는 이유는 `client.ts`의 `errorEnvelopeSchema`와 같다 — 서버가 주는 외부
 * 데이터라 모양을 우리가 보장할 수 없다. `window`는 "어느 상한이냐"가 아니라 "어느 기능이냐"다:
 * 채팅 4경로는 minute/day, 이미지 생성은 image 하나(둘을 가르는 건 `code`), auth 3경로는 auth
 * 하나(둘을 가르는 것도 `code` — `AUTH_LIMIT`/`AUTH_COOLDOWN`)다(BE 주석 RL-11/RL-12, ED-11). */
const rateLimitDetailSchema = z.object({
  code: z.enum(["USER_LIMIT", "QUEUE_FULL", "AUTH_LIMIT", "AUTH_COOLDOWN"]),
  retryAfterSeconds: z.number(),
  window: z.enum(["minute", "day", "image", "auth"]),
});

export type RateLimitDetail = z.infer<typeof rateLimitDetailSchema>;

/** 좁히기 형태는 `entities/legal`의 `isLegalReconsentRequiredError`와 같다(status → detail이
 * object → 내용) — detail이 string인 429(구조화 dict를 쓰지 않는 다른 429)와 반드시 구분돼야 한다.
 *
 * 여기까지가 shared의 몫이다 — BE 계약 그대로의 detail만 준다. "채팅 배너는 minute/day만 말한다"
 * 같은 화면 결정은 `entities/chat-room`의 `chatRateLimit.ts`가 진다(FSD-06). */
export function getRateLimitDetail(error: unknown): RateLimitDetail | null {
  const apiError = isApiError(error) ? error : null;
  if (apiError?.status !== 429 || !apiError.detail || typeof apiError.detail !== "object") return null;
  const parsed = rateLimitDetailSchema.safeParse(apiError.detail);
  return parsed.success ? parsed.data : null;
}
