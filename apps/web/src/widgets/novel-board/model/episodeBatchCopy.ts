/** 화 패널 맨 아래 "이 화가 든 묶음의 동작" 자리의 문장 — 머리, 다시 만들기 안내, 마지막이 아닐 때의 지우기 안내. 구성안으로 쓴 화는
 * 화 하나짜리 묶음이라 "한 번에 만든 화들"이라는 말이 없고, 같은 장면 구성안으로 다시 쓰며, 지우기는 마지막 화 단위다. */
export function toEpisodeBatchCopy({
  isOutlineFlow,
  batchOrdinal,
  rangeLabel,
  episodeCount,
}: {
  isOutlineFlow: boolean;
  /** 상세의 묶음 번호. 묶음이 목록에 없으면(낡은 상세) `undefined`. */
  batchOrdinal: number | undefined;
  /** 묶음에 든 화 범위(`3~5화`). */
  rangeLabel: string;
  episodeCount: number;
}): { heading: string; note: string; notLastHint: string } {
  if (isOutlineFlow) {
    return {
      heading: `구성안으로 쓴 화 · ${rangeLabel}`,
      note: "같은 장면 구성안으로 다시 써요. 고친 화 제목은 다시 만들어도 그대로예요.",
      notLastHint: "지우기는 마지막 화만 할 수 있어요.",
    };
  }
  return {
    heading: batchOrdinal === undefined ? rangeLabel : `묶음 ${batchOrdinal} · ${rangeLabel}`,
    note:
      episodeCount > 1
        ? "한 번에 만든 화들이라 다시 만들거나 지울 때 함께 바뀌어요. 고친 화 제목은 다시 만들어도 그대로예요."
        : "다시 만들어도 고친 화 제목은 그대로예요.",
    notLastHint: "지우기는 마지막 묶음만 할 수 있어요.",
  };
}
