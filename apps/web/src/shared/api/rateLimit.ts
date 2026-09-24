import { z } from "zod";

import { isApiError } from "./client";

/** limit-goal-prompt.md RL-11, error-delivery-goal-prompt.md ED-15 — BE `core/rate_limit_gate.py`와
 * `auth/router.py`가 내는 429 바디 `{"detail": {"code", "retryAfterSeconds", "window"}}`.
 * `Retry-After` 헤더는 일부러 주지 않으므로(CORS에서 못 읽는다) 재시도 시점의 유일한 출처가 이 detail이다.
 *
 * 단언 대신 스키마로 파싱하는 이유는 `client.ts`의 `errorEnvelopeSchema`와 같다 — 서버가 주는 외부
 * 데이터라 모양을 우리가 보장할 수 없다. `window`는 "어느 상한이냐"가 아니라 "어느 기능이냐"다:
 * 채팅 4경로는 minute/clover, 이미지 생성은 image 하나(둘을 가르는 건 `code`), auth 3경로는 auth
 * 하나(둘을 가르는 것도 `code` — `AUTH_LIMIT`/`AUTH_COOLDOWN`)다(BE 주석 RL-11/RL-12, ED-11).
 *
 * 🔴 clover-techspec.md CT-8 — 이 enum 둘이 **1관문**이다. BE가 보내는 값이 여기 없으면
 * `safeParse`가 실패해 아래 `getRateLimitDetail`이 `null`을 돌려주고, 화면은 **429인 줄도 모른 채**
 * 일반 오류 배너로 떨어진다. 그리고 이 계약은 **코드젠을 타지 않는다** — `HTTPException(detail=...)`는
 * OpenAPI 스키마로 나가지 않아 `openapi.json`의 429 선언이 0개이고, BE 리터럴과 이 enum은
 * **수동 사본**이라 불일치를 잡는 CI 게이트가 없다(clover-techspec.md §4-4). 값을 손으로 맞춰야 한다.
 *
 * ⚠️ `window`의 `"day"`는 BE가 더 이상 보내지 않는다(clover-goal-prompt.md CL-1 — 무료 일일분을
 * 넘으면 클로버를 쓰거나 `CLOVER_REQUIRED`가 나간다. `rate_limit_gate.py`에 `"day"` 리터럴 0건).
 * 그래도 **여기서는 지운다** 를 고르지 않았다 — 이 스키마는 외부 데이터 파서라 관대한 쪽이 안전하다.
 * 지웠다가 BE가 롤백 등으로 다시 보내면 **429 전체가 인식되지 않는다**(위 1관문 실패 모드). 화면
 * 결정인 "채팅 배너가 무엇을 말하나"는 `entities/chat-room`의 투영이 지고, 거기서는 `"day"`를 뺐다. */
const rateLimitDetailSchema = z.object({
  code: z.enum([
    "USER_LIMIT",
    "QUEUE_FULL",
    "AUTH_LIMIT",
    "AUTH_COOLDOWN",
    "CLOVER_REQUIRED",
    // clover-goal-prompt.md CL-19 — "부족"이 아니라 **"오늘치 동의가 없다"**다. 둘 다
    // `window: "clover"`(채팅) / `"image"`(이미지)로 오고 `code`로만 갈린다. 화면 동작이
    // 정반대라(배너 vs 모달) 투영이 이 값을 배너 쪽으로 흘리면 안 된다.
    "CLOVER_CONFIRM_REQUIRED",
  ]),
  retryAfterSeconds: z.number(),
  window: z.enum(["minute", "day", "image", "auth", "clover"]),
});

export type RateLimitDetail = z.infer<typeof rateLimitDetailSchema>;

/** 좁히기 형태는 `entities/legal`의 `isLegalReconsentRequiredError`와 같다(status → detail이
 * object → 내용) — detail이 string인 429(구조화 dict를 쓰지 않는 다른 429)와 반드시 구분돼야 한다.
 *
 * 여기까지가 shared의 몫이다 — BE 계약 그대로의 detail만 준다. "채팅 배너는 minute/clover만
 * 말한다" 같은 화면 결정은 `entities/chat-room`의 `chatRateLimit.ts`가 진다(FSD-06). 그래서 위
 * enum은 BE가 낼 수 있는 값을 전부 담고(`"day"` 포함), 투영이 그중 화면이 말할 것만 고른다. */
export function getRateLimitDetail(error: unknown): RateLimitDetail | null {
  const apiError = isApiError(error) ? error : undefined;
  if (apiError?.status !== 429 || !apiError.detail || typeof apiError.detail !== "object") return null;
  const parsed = rateLimitDetailSchema.safeParse(apiError.detail);
  return parsed.success ? parsed.data : null;
}
