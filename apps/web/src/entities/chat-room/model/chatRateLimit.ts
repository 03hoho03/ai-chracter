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

/** limit-goal-prompt.md RL-15/RL-23 — 채팅·미리보기 429 배너 문구. 창마다 다음 행동이 다르므로
 * (몇 초 기다리기 / 내일 다시 오기) 하나로 뭉뚱그리지 않는다.
 *
 * `secondsLeft`를 인자로 받는 이유: minute 창은 배너가 매초 다시 그리는 카운트다운이라 값이 detail의
 * `retryAfterSeconds`가 아니라 **지금 남은 초**다. day 창은 `retryAfterSeconds`가 최대 86400이라
 * 초 타이머를 걸지 않고 "자정"이라는 고정 시점으로 말한다. */
export function formatChatRateLimitMessage(
  rateLimit: ChatRateLimit,
  surface: "chat" | "preview",
  secondsLeft: number,
): string {
  switch (rateLimit.window) {
    case "minute":
      return `${surface === "preview" ? PREVIEW_LEAD : "너무 빠르게 보냈어요"} · ${secondsLeft}초 뒤 다시`;
    case "day":
      return `${surface === "preview" ? PREVIEW_LEAD : "오늘 대화 한도에 닿았어요"} · 자정에 다시 열려요`;
    default:
      return assertNever(rateLimit.window);
  }
}
