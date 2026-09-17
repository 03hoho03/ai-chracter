import type { RateLimitDetail } from "@/shared/api/rateLimit";
import { assertNever } from "@/shared/lib/assertNever";

/** 이미지 생성 429 토스트 문구. 두 코드는 사용자가 할 일이 다르다 — `USER_LIMIT`은 토큰이 다시
 * 찰 때까지 기다리는 것이고, `QUEUE_FULL`은 자기 잡이 끝나면 곧바로 다시 되는 것이라 남은 시간을
 * 약속하지 않는다(BE가 주는 60초는 큐 길이가 아니라 잡 하나의 최대 소요라 "약 1분"이라고 말하면
 * 거짓이 된다).
 *
 * `USER_LIMIT`의 `retryAfterSeconds`는 ≤ 7200이다 — BE `take_tokens`가
 * `ceil((count - tokens) * 3600)`을 돌려주고 `count` 상한이 2라(images/schemas.py `le=2`) 천장이
 * 2 × 3600이다. 그래서 이 초는 **한 장**이 아니라 **요청한 장수**를 다시 살 수 있게 되는 시각이고,
 * 문구도 "한 장 더"를 약속하지 않는다(한 장은 그보다 먼저 살 수 있다). */
export function formatImageRateLimitMessage(detail: RateLimitDetail): string {
  switch (detail.code) {
    case "USER_LIMIT": {
      // 올림이다 — 이 숫자는 대기 약속이라 내림 오차(89초를 "1분")가 그대로 재실패가 된다.
      const minutes = Math.max(1, Math.ceil(detail.retryAfterSeconds / 60));
      return `이미지 생성 한도에 닿았어요 · 약 ${minutes}분 뒤 다시 시도할 수 있어요`;
    }
    case "QUEUE_FULL":
      return "지금 만들고 있는 이미지가 있어요 · 잠시 뒤 다시 시도해 주세요";
    default:
      return assertNever(detail.code);
  }
}
