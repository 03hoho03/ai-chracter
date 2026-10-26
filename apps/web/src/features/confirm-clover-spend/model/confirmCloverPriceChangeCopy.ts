import type { CloverSpendSurface } from "./confirmCloverSpendCopy";

/** 가격 바뀜 확인 모달의 본문과 확인 버튼. 금액은 서버가 거절에 실어 보낸 그 요청의 총액이다(이미지는 장수를 곱한 값이라
 * "한 번에 N개씩"이 아니다). 모르면 숫자 없이 묻는다 — 화면이 가격 숫자의 사본을 두지 않는다. 동사는 표면마다 그
 * 화면의 행동(보내기·만들기)을 따른다. */
export function cloverPriceChangeCopy(
  surface: CloverSpendSurface,
  cost: number | undefined,
): { description: string; confirmLabel: string } {
  const verb = surface === "chat" ? { ask: "보낼까요", label: "보내기" } : { ask: "만들까요", label: "만들기" };
  const spend =
    cost === undefined ? "바뀐 가격으로 클로버가 차감돼요." : `지금 가격으로는 클로버 ${cost.toLocaleString()}개가 차감돼요.`;
  return { description: `${spend} 이대로 ${verb.ask}?`, confirmLabel: `새 가격으로 ${verb.label}` };
}
