/** 요약 칸의 두 문장 — 요약이 아직 없을 때와, 요약이 어떻게 바뀌는지 알리는 안내. 긴 대화를 요약으로 접는 서버 스위치
 * (`features.summaryFolding`)가 꺼져 있으면 새 요약이 생기지 않고 있는 요약도 응답에 쓰이지 않으며, 응답에는 지난 대화가
 * 접히지 않고 그대로 실린다 — 그때 "AI가 다시 정리해요"라고 말하면 사실과 다르다. */
export function summaryFoldingCopy(isFolding: boolean): { emptySummary: string; foldingHint: string } {
  if (isFolding) {
    return {
      emptySummary: "아직 요약할 만큼 대화가 쌓이지 않았어요. 최근 대화는 전부 기억 중이에요.",
      foldingHint: "대화를 이어 가면 AI가 이 요약을 다시 정리해요. 꼭 지켜야 할 내용은 ‘꼭 기억할 것’에 적어 주세요.",
    };
  }
  return {
    emptySummary: "지금은 대화를 요약으로 정리하지 않아요.",
    foldingHint: "지금은 대화를 요약으로 정리하지 않고, 요약도 응답에 쓰이지 않아요. 지난 대화는 그대로 기억하고 있어요.",
  };
}
