/** 화 다시 만들기 금액 확인의 설명. 다시 만들기는 한 번에 만든 화들(묶음)을 함께 새로 쓰므로, 여러 화면 어느 화들이
 * 바뀌는지와 화 수가 그대로라는 것을 먼저 말한다. 다시 만든 글이 새 판이 되면 서버가 그 화들의 적용하지 않은 AI
 * 수정안을 지운다(환불 없음) — 같은 일을 하는 직접 저장·판 되돌리기와 같은 경고를 그 수정안이 있을 때만 덧붙인다. */
export function toRegenerateConfirmDescription({
  rangeLabel,
  episodeCount,
  hasPendingAiEdits,
}: {
  /** 함께 바뀌는 화들의 이름(`3~5화`). */
  rangeLabel: string;
  episodeCount: number;
  hasPendingAiEdits: boolean;
}): string {
  const isSingle = episodeCount <= 1;
  const base = isSingle
    ? "같은 대화로 이 화를 새로 써요. 지금 글은 이력에 남아요."
    : `같은 대화로 함께 만든 ${rangeLabel}를 모두 새로 써요. 화 수는 그대로이고 지금 글은 이력에 남아요.`;
  if (!hasPendingAiEdits) return base;
  const where = isSingle ? "이 화" : "이 화들";
  return `${base} 다시 만들면 ${where}에서 적용하지 않은 AI 수정안은 사라지고, 쓴 클로버는 돌아오지 않아요.`;
}
