import { toOverCapPhrase, toTurnCapFit, type ChapterModelOption, type ChapterTurnCap } from "@/entities/novel";

/** 장면 구성안 만들기 확인 창의 한 줄 — 이 화의 지금 턴 수로는 원고를 못 쓰는 모델이 있으면 그 사정과 두 길(구성안에서 화 나누기,
 * 장면 구성안에서 장면 덜기)을 말한다. 장면 구성안을 산 뒤 화를 나누면 그 장면 구성안이 낡아 다시 사야 해서, 사기 전에 알린다.
 * 장면 구성안이 턴을 덜 수 있어 "이대로는"이라고 말한다. 모두 맞거나 턴 수를 모르면 없다. */
export function toSceneOutlineTurnNote(
  turnCount: number | null | undefined,
  caps: readonly ChapterTurnCap[],
): string | undefined {
  const fit = toTurnCapFit(turnCount, caps);
  if (fit === undefined || turnCount === null || turnCount === undefined || fit.kind === "fits") return undefined;
  const turns = `${turnCount.toLocaleString()}턴`;
  if (fit.kind === "some") {
    return `이 화는 ${turns}이라 이대로는 원고를 ${fit.ableNames.join("·")} 로만 쓸 수 있어요(${toOverCapPhrase(fit.over)}). 다른 모델로 쓰려면 먼저 구성안에서 화를 나누거나, 장면 구성안에서 장면을 덜어주세요.`;
  }
  return `이 화는 ${turns}이라 이대로는 어느 모델로도 원고를 쓸 수 없어요(${fit.maxTurns.toLocaleString()}턴까지). 먼저 구성안에서 화를 나누거나, 장면 구성안에서 장면을 덜어주세요.`;
}

/** 원고 확인 창 대신 보일 안내 — 고를 수 있는 모델이 하나도 없으면(모두 장면 턴 수가 상한을 넘음) 창을 열어 봐야 누를 것이 없다.
 * 목록이 비었으면 여기서 말하지 않는다(호출부가 따로 다룬다). */
export function toNoWritableModelRefusal(
  options: readonly ChapterModelOption[],
  turnCount: number | null | undefined,
): string | undefined {
  if (options.length === 0 || options.some((option) => option.disabledReason === undefined)) return undefined;
  const subject =
    turnCount === null || turnCount === undefined
      ? "지금 고를 수 있는 모델로는 이 화의 원고를 쓸 수 없어요."
      : `이 화는 ${turnCount.toLocaleString()}턴이라 지금 고를 수 있는 모델로는 원고를 쓸 수 없어요.`;
  return `${subject} 구성안에서 화를 나누거나 장면 구성안에서 장면을 덜어주세요.`;
}
