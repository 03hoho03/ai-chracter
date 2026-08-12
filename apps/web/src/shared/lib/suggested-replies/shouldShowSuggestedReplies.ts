// 초기 선택지(오프닝 칩) 노출 판정. 채팅방(ChatRoomView)과 미리보기(PreviewSessionView)가
// 공유하는 단일 진실 공급원 — 두 화면이 각자 인라인 조건을 들고 어긋나는 것을 막는다.
// 서버 turn_count는 0에서 시작하고 오프닝 메시지로는 오르지 않으므로,
// turnCount === 0이 "아직 첫 턴을 보내지 않은 상태"다.
export function shouldShowSuggestedReplies(suggestedReplies: string[], turnCount: number): boolean {
  return suggestedReplies.length > 0 && turnCount === 0;
}
