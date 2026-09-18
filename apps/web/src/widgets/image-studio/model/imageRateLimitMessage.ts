import { getRateLimitDetail } from "@/shared/api/rateLimit";
import { assertNever } from "@/shared/lib/assertNever";

/** 이미지 429(`window: "image"`)만 좁힌 타입 — `code`가 이미지 코드 2종으로 좁혀져야
 * `assertNever`가 다시 총망라(exhaustive)가 된다(ED-17). `window`를 `"image"`로 좁혀서 그대로 남기는
 * 이유: 아래 테스트의 기존 리터럴이 `window: "image"`를 이미 채워서 넘긴다 — 필드를 뺐다면 그
 * 리터럴들이 초과 속성 검사(excess property check)에 걸려 무변경으로 못 남는다. */
export type ImageRateLimit = { code: "USER_LIMIT" | "QUEUE_FULL"; retryAfterSeconds: number; window: "image" };

/** shared는 BE 계약 그대로의 제네릭 `RateLimitDetail`만 준다(`shared/api/rateLimit.ts`) — "이미지
 * 429만 이 위젯이 받는다"는 화면 결정이라 shared가 알 일이 아니다(`entities/chat-room`의
 * `getChatRateLimit`과 같은 이유, FSD-06). `code` enum이 auth 2종으로 늘면서 `RateLimitDetail`을
 * 그대로 포매터에 넘기던 낡은 경로가 컴파일이 안 됐다 — 이 투영이 그 강제 동반 변경이다.
 *
 * 두 `if`로 나눈 이유: `window`·`code` 가드를 통과해도 TS는 `detail`(변수 전체)의 타입을 판별
 * 유니언처럼 좁혀 주지 않는다(플랫 객체 타입이라 프로퍼티별 CFA 좁히기가 전체 타입에 반영되지
 * 않는다 — 실측) → `detail`을 그대로 반환하면 컴파일이 안 되고, 좁혀진 프로퍼티 접근값으로
 * 리터럴을 다시 지어야 한다(`entities/chat-room`의 `getChatRateLimit`과 같은 이유로 재구성한다). */
export function getImageRateLimit(error: unknown): ImageRateLimit | undefined {
  const detail = getRateLimitDetail(error);
  if (detail === null || detail.window !== "image") return undefined;
  if (detail.code !== "USER_LIMIT" && detail.code !== "QUEUE_FULL") return undefined;
  return { code: detail.code, retryAfterSeconds: detail.retryAfterSeconds, window: detail.window };
}

/** 이미지 생성 429 토스트 문구. 두 코드는 사용자가 할 일이 다르다 — `USER_LIMIT`은 토큰이 다시
 * 찰 때까지 기다리는 것이고, `QUEUE_FULL`은 자기 잡이 끝나면 곧바로 다시 되는 것이라 남은 시간을
 * 약속하지 않는다(BE가 주는 60초는 큐 길이가 아니라 잡 하나의 최대 소요라 "약 1분"이라고 말하면
 * 거짓이 된다).
 *
 * `USER_LIMIT`의 `retryAfterSeconds`는 ≤ 7200이다 — BE `take_tokens`가
 * `ceil((count - tokens) * 3600)`을 돌려주고 `count` 상한이 2라(images/schemas.py `le=2`) 천장이
 * 2 × 3600이다. 그래서 이 초는 **한 장**이 아니라 **요청한 장수**를 다시 살 수 있게 되는 시각이고,
 * 문구도 "한 장 더"를 약속하지 않는다(한 장은 그보다 먼저 살 수 있다). */
export function formatImageRateLimitMessage(detail: ImageRateLimit): string {
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
