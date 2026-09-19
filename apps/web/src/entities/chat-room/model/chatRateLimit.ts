import { getRateLimitDetail } from "@/shared/api/rateLimit";
import { assertNever } from "@/shared/lib/assertNever";

/** 채팅 4경로(전송·재생성·편집·미리보기)의 429. 창이 minute/clover 둘뿐이라 배너 문구도 둘뿐이다.
 * 이 투영은 shared가 아니라 이 슬라이스에 있다 — "채팅 배너는 minute/clover만 말한다"는 화면 결정이라
 * shared가 알 일이 아니다(`shared/api/rateLimit.ts`에는 BE 계약 그대로인 제네릭만 남는다).
 *
 * 🔴 clover-techspec.md §5-6 / S9-3a — `"day"`를 뺐다. clover-goal-prompt.md CL-1로 무료 일일분을
 * 넘기면 클로버를 쓰거나(성공) `CLOVER_REQUIRED`가 나가므로 **BE가 `window: "day"`를 더 이상 보내지
 * 않는다**(`core/rate_limit_gate.py`에 `"day"` 리터럴 0건 — 채팅이 내는 창은 `"minute"`과 `"clover"`
 * 둘뿐이다). 남겨 두면 "이 문구가 언제 나오는가"에 답할 수 없는 죽은 코드가 된다. */
export type ChatRateLimit = { window: "minute" | "clover"; retryAfterSeconds: number };

/** 채팅이 말할 문구가 없는 창(현재 `image`·`auth`·`day`)은 undefined로 떨어져 기존 일반 오류 배너가
 * 받는다. 허용 목록(minute/clover만 통과)인 이유: 배제 목록이면 `window` enum에 값이 늘 때마다
 * 조용히 새 값이 채팅 배너로 새 나간다 — 허용 목록은 값이 늘어도 기본이 "안 받는다"다(ED-16).
 *
 * ⚠️ 🔴 **이 허용 목록은 `assertNever`가 잡아 주지 않는다.** 아래 두 포매터의 `switch`는 유니언에서
 * `"day"`를 빼는 순간 컴파일이 깨지지만, 여기는 평범한 `if`라 `"day"`를 남겨 뒀어도 타입 에러가
 * 나지 않는다 — 값이 통과해 `ChatRateLimit`에 없는 `window`가 실린 객체가 만들어질 뿐이다.
 * 그래서 이 줄은 손으로 고쳐야 하고, `chatRateLimit.test.ts`가 런타임 단언으로 고정한다. */
export function getChatRateLimit(error: unknown): ChatRateLimit | undefined {
  const detail = getRateLimitDetail(error);
  if (detail === null || (detail.window !== "minute" && detail.window !== "clover")) return undefined;
  return { window: detail.window, retryAfterSeconds: detail.retryAfterSeconds };
}

/** 미리보기는 실제 채팅과 같은 상한을 공유한다(BE는 채팅 4경로에 같은 게이트를 건다) — 빌더에서
 * 갑자기 막히면 "미리보기만의 제약"으로 읽히므로 그 사실을 문구가 먼저 말한다(RL-23). */
const PREVIEW_LEAD = "미리보기도 채팅과 같은 한도를 써요";

function minuteLead(surface: "chat" | "preview"): string {
  return surface === "preview" ? PREVIEW_LEAD : "너무 빠르게 보냈어요";
}

/** clover-techspec.md CT-8 — 문구가 **두 사실을 함께** 말한다: 지금 막힌 이유(클로버가 없다)와
 * 다시 되는 시점(자정에 무료 한도가 돌아온다). 하나만 말하면 사용자가 할 수 있는 일이 안 보인다.
 *
 * `retryAfterSeconds`는 KST 자정까지 남은 초라 **참값이다** — 그때 무료 일일분이 돌아오므로 실제로
 * 다시 보낼 수 있다(BE `_too_many_requests(..., seconds_until_kst_midnight(now), ...)`). 다만 최대
 * 86400이라 초 타이머를 걸지 않고 "자정"이라는 고정 시점으로 말한다. 카운트다운이 없어
 * `formatChatRateLimitMessage`와 `formatChatRateLimitAnnouncement`가 이 문구를 그대로 공유한다
 * (ED-7 — 사본을 두지 않는다). */
function cloverMessage(surface: "chat" | "preview"): string {
  return `${surface === "preview" ? PREVIEW_LEAD : "클로버가 없어요"} · 자정에 무료 한도가 돌아와요`;
}

/** limit-goal-prompt.md RL-15/RL-23 — 채팅·미리보기 429 배너 문구. 창마다 다음 행동이 다르므로
 * (몇 초 기다리기 / 자정까지 기다리거나 클로버를 채우기) 하나로 뭉뚱그리지 않는다.
 *
 * `secondsLeft`를 인자로 받는 이유: minute 창은 배너가 매초 다시 그리는 카운트다운이라 값이 detail의
 * `retryAfterSeconds`가 아니라 **지금 남은 초**다. clover 창은 `retryAfterSeconds`가 최대 86400이라
 * 초 타이머를 걸지 않고 "자정"이라는 고정 시점으로 말한다.
 *
 * `secondsLeft === 0`에서 `${secondsLeft}초 뒤 다시`를 그대로 쓰면 "0초 뒤 다시"가 남는다(ED-10,
 * 실서버 관측). 그 시점엔 버튼이 이미 `aria-disabled=false`로 풀려 클릭이 통하므로(S8-8) 문구도
 * "지금 다시 보낼 수 있다"를 말해야 한다. */
export function formatChatRateLimitMessage(
  rateLimit: ChatRateLimit,
  surface: "chat" | "preview",
  secondsLeft: number,
): string {
  switch (rateLimit.window) {
    case "minute":
      return secondsLeft === 0
        ? `${minuteLead(surface)} · 이제 다시 보낼 수 있어요`
        : `${minuteLead(surface)} · ${secondsLeft}초 뒤 다시`;
    case "clover":
      return cloverMessage(surface);
    default:
      return assertNever(rateLimit.window);
  }
}

/** ED-7 — `RateLimitNotice`의 `role="alert"` `sr-only` 쌍둥이가 읽을 문장. `secondsLeft`를 인자로
 * 받지 않는 것이 설계의 핵심이다 — 숫자가 없으면 마운트 1회 말고는 반환값이 바뀔 길이 없어(뮤테이션이
 * 원리적으로 불가능해) alert가 매초 재발화하지 않는다. clover 문구는 `cloverMessage`를 공유한다. */
export function formatChatRateLimitAnnouncement(rateLimit: ChatRateLimit, surface: "chat" | "preview"): string {
  switch (rateLimit.window) {
    case "minute":
      return `${minuteLead(surface)} · 잠시 뒤 다시 보낼 수 있어요`;
    case "clover":
      return cloverMessage(surface);
    default:
      return assertNever(rateLimit.window);
  }
}
