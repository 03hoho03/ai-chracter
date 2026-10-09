/** 청약철회 목록의 "결제 전에 먼저 써 볼 수 있다" 문장.
 *
 * 결제 전에 실제로 써 볼 수 있는 것은 하루 무료 대화와 미션 클로버다. 무료 대화 수는 서버가 정하므로 숫자를 여기 적지
 * 않고 가격 응답의 `dailyFreeChatTurns` 를 받는다. 값이 없거나 0이면(새 필드가 없는 옛 API 응답, 또는 무료 대화를 끈
 * 경우) 있지도 않은 무료 대화를 약속하지 않도록 미션 클로버만 말한다.
 *
 * 미인증 회원 게이트가 켜지면 무료 대화·미션은 본인인증한 회원만 받으므로 그 조건을 함께 말한다(결제도 본인인증한
 * 회원만 할 수 있어 "인증한 회원은 결제 전에 써 볼 수 있다"는 참이다). 게이트가 꺼진 동안은 아무도 인증할 필요가
 * 없으니 조건을 붙이면 거짓이다 — 그래서 게이트 값(가격 응답의 `identityGateEnabled`)으로 가른다. 값을 아직 못
 * 받았으면 꺼진 것으로 본다(배포 기본값이다). */
export function formatTrialSentence(identityGateEnabled: boolean, dailyFreeChatTurns: number | undefined): string {
  const means =
    dailyFreeChatTurns !== undefined && dailyFreeChatTurns > 0
      ? `하루 ${dailyFreeChatTurns.toLocaleString()}턴의 무료 대화와 미션 클로버로`
      : "미션 클로버로";
  return identityGateEnabled
    ? `본인인증을 마친 회원은 결제하기 전에 ${means} 서비스를 먼저 써 볼 수 있어요.`
    : `결제하기 전에 ${means} 서비스를 먼저 써 볼 수 있어요.`;
}
