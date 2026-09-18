import { getRateLimitDetail } from "@/shared/api/rateLimit";
import { assertNever } from "@/shared/lib/assertNever";

/** 채팅 4경로(전송·재생성·편집·미리보기)의 429. 창이 minute/day 둘뿐이라 배너 문구도 둘뿐이다.
 * 이 투영은 shared가 아니라 이 슬라이스에 있다 — "채팅 배너는 minute/day만 말한다"는 화면 결정이라
 * shared가 알 일이 아니다(`shared/api/rateLimit.ts`에는 BE 계약 그대로인 제네릭만 남는다). */
export type ChatRateLimit = { window: "minute" | "day"; retryAfterSeconds: number };

/** 채팅이 말할 문구가 없는 창(현재 `image`·`auth`)은 undefined로 떨어져 기존 일반 오류 배너가
 * 받는다. 허용 목록(minute/day만 통과)인 이유: 배제 목록이면 `window` enum에 값이 늘 때마다
 * 조용히 새 값이 채팅 배너로 새 나간다 — 허용 목록은 값이 늘어도 기본이 "안 받는다"다(ED-16). */
export function getChatRateLimit(error: unknown): ChatRateLimit | undefined {
  const detail = getRateLimitDetail(error);
  if (detail === null || (detail.window !== "minute" && detail.window !== "day")) return undefined;
  return { window: detail.window, retryAfterSeconds: detail.retryAfterSeconds };
}

/** 미리보기는 실제 채팅과 같은 상한을 공유한다(BE는 채팅 4경로에 같은 게이트를 건다) — 빌더에서
 * 갑자기 막히면 "미리보기만의 제약"으로 읽히므로 그 사실을 문구가 먼저 말한다(RL-23). */
const PREVIEW_LEAD = "미리보기도 채팅과 같은 한도를 써요";

function minuteLead(surface: "chat" | "preview"): string {
  return surface === "preview" ? PREVIEW_LEAD : "너무 빠르게 보냈어요";
}

/** day 창은 `retryAfterSeconds`가 최대 86400이라 초 타이머를 걸지 않고 "자정"이라는 고정 시점으로
 * 말한다. 카운트다운이 없어 `formatChatRateLimitMessage`와 `formatChatRateLimitAnnouncement`가
 * 이 문구를 그대로 공유한다(ED-7 — 사본을 두지 않는다). */
function dayMessage(surface: "chat" | "preview"): string {
  return `${surface === "preview" ? PREVIEW_LEAD : "오늘 대화 한도에 닿았어요"} · 자정에 다시 열려요`;
}

/** limit-goal-prompt.md RL-15/RL-23 — 채팅·미리보기 429 배너 문구. 창마다 다음 행동이 다르므로
 * (몇 초 기다리기 / 내일 다시 오기) 하나로 뭉뚱그리지 않는다.
 *
 * `secondsLeft`를 인자로 받는 이유: minute 창은 배너가 매초 다시 그리는 카운트다운이라 값이 detail의
 * `retryAfterSeconds`가 아니라 **지금 남은 초**다. day 창은 `retryAfterSeconds`가 최대 86400이라
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
    case "day":
      return dayMessage(surface);
    default:
      return assertNever(rateLimit.window);
  }
}

/** ED-7 — `RateLimitNotice`의 `role="alert"` `sr-only` 쌍둥이가 읽을 문장. `secondsLeft`를 인자로
 * 받지 않는 것이 설계의 핵심이다 — 숫자가 없으면 마운트 1회 말고는 반환값이 바뀔 길이 없어(뮤테이션이
 * 원리적으로 불가능해) alert가 매초 재발화하지 않는다. day 문구는 `dayMessage`를 공유한다(사본 없음). */
export function formatChatRateLimitAnnouncement(rateLimit: ChatRateLimit, surface: "chat" | "preview"): string {
  switch (rateLimit.window) {
    case "minute":
      return `${minuteLead(surface)} · 잠시 뒤 다시 보낼 수 있어요`;
    case "day":
      return dayMessage(surface);
    default:
      return assertNever(rateLimit.window);
  }
}
