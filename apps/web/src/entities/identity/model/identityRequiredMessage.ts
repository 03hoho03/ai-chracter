/** 왜 본인인증이 필요한지는 자리마다 다르다. 출석·미션은 인증하면 **받는 것**이 생기고, 구매는 인증해야
 * **할 수 있는 것**이다 — 구매 자리에 받는 것을 쓰면 받을 수 있는 회원이 구매 조건으로 읽는다. `attendance` 는
 * 출석판 화면 자리다(출석 보상은 게이트 스위치와 무관하게 인증한 회원에게만 지급된다). */
export type IdentityRequiredReason = "free-rewards" | "purchase" | "attendance";

/** 안내 문장. 하루 무료 대화는 없다 — 인증하면 받는 것은 매일 출석 클로버와 미션 클로버다. */
export function formatIdentityRequiredMessage(reason: IdentityRequiredReason): string {
  if (reason === "purchase") return "클로버를 구매하려면 본인인증이 필요해요. 만 19세 이상만 구매할 수 있어요.";
  if (reason === "attendance") return "출석 보상을 받으려면 본인인증이 필요해요.";
  return "본인인증을 하면 매일 출석 클로버와 미션 클로버를 받을 수 있어요.";
}
