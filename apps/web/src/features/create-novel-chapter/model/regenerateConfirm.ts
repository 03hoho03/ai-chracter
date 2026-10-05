/** 장 다시 만들기 금액 확인의 설명. 다시 만든 글이 새 판이 되면 서버가 그 장의 적용하지 않은 AI 수정안을 지운다(환불
 * 없음) — 같은 일을 하는 직접 저장·판 되돌리기와 같은 경고를 그 수정안이 있을 때만 덧붙인다. */
export function toRegenerateConfirmDescription(hasPendingAiEdits: boolean): string {
  const base = "같은 대화로 이 장을 새로 써요. 지금 글은 이력에 남아요.";
  if (!hasPendingAiEdits) return base;
  return `${base} 다시 만들면 이 장에서 적용하지 않은 AI 수정안은 사라지고, 쓴 클로버는 돌아오지 않아요.`;
}
