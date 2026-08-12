// 초기 선택지(오프닝 칩) 노출 판정. 채팅방(ChatRoomView)과 미리보기(PreviewSessionView)가
// 공유하는 단일 진실 공급원 — 두 화면이 각자 인라인 조건을 들고 어긋나는 것을 막는다.
//
// turnCount만으로는 부족하다. 서버의 turn_count는 "대화가 시작됐는가"가 아니라 **성공한 턴 수**다
// — 사용자 메시지는 Gemini 호출 전에 커밋되지만(생성이 실패해도 입력을 잃지 않게, US-053 AC)
// turn_count += 1은 생성에 성공한 뒤에만 실행된다. 그래서 생성이 실패한 방은 사용자 발화가
// 쌓여도 turn_count가 0에 머문다(dev DB 실측: turn_count=0인 방 38개 중 31개에 사용자 발화가
// 있었다). 그런 방에서 turnCount만 보면 오프닝 칩이 다시 살아난다.
//
// hasUserMessage는 그 구멍을 덮으면서 스트리밍 구간도 함께 해결한다 — 사용자 메시지는 전송
// 즉시 캐시에 낙관적으로 추가되므로, turn_count가 오르기를 기다리지 않고 그 순간 칩이 사라진다.
export function shouldShowSuggestedReplies(
  suggestedReplies: string[],
  turnCount: number,
  hasUserMessage: boolean,
): boolean {
  return suggestedReplies.length > 0 && turnCount === 0 && !hasUserMessage;
}
