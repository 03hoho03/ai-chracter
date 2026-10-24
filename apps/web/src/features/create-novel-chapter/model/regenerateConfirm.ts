/** 화 다시 만들기 금액 확인의 설명. 다시 만들기는 한 번에 만든 화들(묶음)을 함께 새로 쓰므로, 여러 화면 어느 화들이
 * 바뀌는지와 화 수가 그대로라는 것을 먼저 말한다. 다시 만든 글이 새 판이 되면 서버가 그 화들의 적용하지 않은 AI
 * 수정안을 지운다(환불 없음) — 같은 일을 하는 직접 저장·판 되돌리기와 같은 경고를 그 수정안이 있을 때만 덧붙인다.
 * 다시 만든 판은 문단이 모두 새 문단이라 붙여 둔 삽화가 자리를 잃는다 — 삽화를 쓸 수 있을 때만 그것도 말한다(화 요약에는
 * 삽화 수가 없어 붙인 삽화가 있는지는 가르지 않는다). */
export function toRegenerateConfirmDescription({
  rangeLabel,
  episodeCount,
  hasPendingAiEdits,
  isIllustrationsOn = false,
  isOutlineFlow = false,
}: {
  /** 함께 바뀌는 화들의 이름(`3~5화`). */
  rangeLabel: string;
  episodeCount: number;
  hasPendingAiEdits: boolean;
  /** 삽화 스위치가 켜져 있는가(`isNovelIllustrationsOn`). */
  isIllustrationsOn?: boolean;
  /** 구성안(장면 구성안)으로 쓴 화인가 — 같은 대화가 아니라 같은 장면 구성안으로 다시 쓴다. 구성안으로 쓴 화는 늘 한 화다. */
  isOutlineFlow?: boolean;
}): string {
  const isSingle = episodeCount <= 1;
  const base = toBaseSentence({ rangeLabel, isSingle, isOutlineFlow });
  const where = isSingle ? "이 화" : "이 화들";
  const pending = hasPendingAiEdits
    ? ` 다시 만들면 ${where}에서 적용하지 않은 AI 수정안은 사라지고, 쓴 클로버는 돌아오지 않아요.`
    : "";
  const illustrations = isIllustrationsOn ? " 넣어 둔 삽화는 자리를 잃고 위치 확인 필요로 옮겨져요." : "";
  return `${base}${pending}${illustrations}`;
}

function toBaseSentence({
  rangeLabel,
  isSingle,
  isOutlineFlow,
}: {
  rangeLabel: string;
  isSingle: boolean;
  isOutlineFlow: boolean;
}): string {
  if (isOutlineFlow) return "같은 장면 구성안으로 이 화를 새로 써요. 지금 글은 이력에 남아요.";
  return isSingle
    ? "같은 대화로 이 화를 새로 써요. 지금 글은 이력에 남아요."
    : `같은 대화로 함께 만든 ${rangeLabel}를 모두 새로 써요. 화 수는 그대로이고 지금 글은 이력에 남아요.`;
}
