/** 쓰임새 절 첫 줄 — 하루 무료 대화와 무료분을 다 쓴 뒤의 기본 모델 대화 단가.
 *
 * 무료분은 기본 모델 대화에만 있다(상위 모델 턴은 첫 턴부터 클로버를 쓴다). 미인증 회원 게이트가 켜지면 본인인증하지
 * 않은 회원의 무료분은 0이라 대상을 인증한 회원으로 좁히고, 꺼진 동안은 조건을 붙이지 않는다 — 게이트 값(가격 응답의
 * `identityGateEnabled`)으로 가르는 이유다. 무료 대화 수와 단가는 숫자를 여기 적지 않고 가격 응답 값을 받는다. 무료
 * 대화 수가 없거나 0이면(새 필드가 없는 옛 API 응답, 또는 무료 대화를 끈 경우) 약속할 무료 대화가 없어 `null` 이다. */
export function formatFreeChatSentence(
  identityGateEnabled: boolean,
  dailyFreeChatTurns: number | undefined,
  chatTurnCost: number,
): string | null {
  if (dailyFreeChatTurns === undefined || dailyFreeChatTurns <= 0) return null;
  const turns = dailyFreeChatTurns.toLocaleString();
  const afterwards = `그 뒤에는 1턴에 클로버 ${chatTurnCost.toLocaleString()}개가 들어요.`;
  return identityGateEnabled
    ? `본인인증을 마친 회원은 기본 모델 대화를 하루 ${turns}턴까지 무료로 할 수 있어요. ${afterwards}`
    : `기본 모델 대화는 하루 ${turns}턴까지 무료예요. ${afterwards}`;
}
