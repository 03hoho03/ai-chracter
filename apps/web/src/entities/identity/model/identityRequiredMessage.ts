/** 왜 본인인증이 필요한지는 자리마다 다르다. 무료 대화·미션·출석은 인증하면 **받는 것**이 생기고, 구매는 인증해야
 * **할 수 있는 것**이다 — 구매 자리에 "무료 대화를 받는다"를 쓰면 게이트가 꺼진 동안 거짓이 된다. `attendance` 는
 * 출석판 화면 자리다(출석 보상은 게이트 스위치와 무관하게 인증한 회원에게만 지급된다). */
export type IdentityRequiredReason = "free-rewards" | "purchase" | "attendance";

/** 안내 문장. 하루 무료 대화 수는 서버가 `GET /me` 로 주는 게이트 상수다 — 웹에 숫자 사본을 두면 한도를 바꿀 때 이
 * 문장만 거짓으로 남는다. 세션을 아직 못 읽었으면 숫자 없이 말한다.
 *
 * `attendanceEnabled` 는 공개 가격 응답의 출석판 스위치다(못 받았으면 꺼짐). 출석판이 켜지면 서버가 하루 무료 대화를
 * 없애므로 무료 대화 대신 출석 클로버를 말한다. 꺼진 동안에도 무료 대화 수가 0 이면 무료 대화를 말하지 않는다 —
 * 켜졌는데 가격 응답이 늦게 오는 순간 "무료 대화 0턴" 이라는 없는 약속이 나가지 않게 하려는 것이다. */
export function formatIdentityRequiredMessage(
  reason: IdentityRequiredReason,
  dailyFreeChatTurns: number | undefined,
  attendanceEnabled = false,
): string {
  if (reason === "purchase") return "클로버를 구매하려면 본인인증이 필요해요. 만 19세 이상만 구매할 수 있어요.";
  if (reason === "attendance") return "출석 보상을 받으려면 본인인증이 필요해요.";
  if (attendanceEnabled) return "본인인증을 하면 매일 출석 클로버와 미션 클로버를 받을 수 있어요.";
  if (dailyFreeChatTurns === 0) return "본인인증을 하면 미션 클로버를 받을 수 있어요.";
  // 조사는 앞말 받침을 따른다("대화와" / "30턴과").
  const freeChat = dailyFreeChatTurns === undefined ? "매일 무료 대화와" : `매일 무료 대화 ${dailyFreeChatTurns}턴과`;
  return `본인인증을 하면 ${freeChat} 미션 클로버를 받을 수 있어요.`;
}
