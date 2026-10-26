import { isCloverInsufficient } from "@/entities/clover";

/** 이미지의 클로버 금액은 공개 가격 응답의 장당 가격(`imageCost`)에서 온다 — 웹은 그 숫자의 사본을 두지 않는다. 그 응답을
 * 아직 못 받았거나 받지 못했으면 단가가 undefined 다.
 *
 * 단가를 모를 때 부족하다고 하지 않는다. 이 판정은 잔량을 부족 잉크로 칠하는 안내일 뿐 생성을 막지 않고, 정말 모자라면
 * 서버가 생성 요청을 거절해 그 안내가 따로 뜬다. 반대로 모르는 채 부족이라 칠하면 넉넉한 사람에게 거짓 경고를 보인다.
 * "한 장도 못 만드는가"가 기준이라 장수를 곱하지 않는다. */
export function isImageCloverShort(balance: number, imageCost: number | undefined): boolean {
  return imageCost !== undefined && isCloverInsufficient(balance, imageCost);
}

/** 한 요청의 금액(장수 × 장당 가격) — 서버 게이트의 계산과 같다. 단가를 모르면 금액도 모르고, 확인 모달이 숫자 없이 말한다. */
export function imageRequestCloverCost(count: number, imageCost: number | undefined): number | undefined {
  return imageCost === undefined ? undefined : count * imageCost;
}

/** 생성 버튼 옆에 늘 보이는 금액 안내. 서버는 무료 생성 횟수가 이번 장수만큼 남아 있으면 클로버를 깎지 않고, 모자라면
 * 그 요청 전체를 클로버로 받는다(일부만 무료로 치지 않는다). 웹은 남은 무료 생성 횟수를 알 수 없으므로 "모자라면"이라는
 * 조건으로 말한다 — 무조건 깎인다고 하면 무료로 만드는 사람에게 거짓이 된다. 단가를 모르면 숫자 없는 문장을 보이지 않고
 * 안내 자체를 숨긴다(부족 판정을 생략하는 것과 같은 이유). */
export function formatImageCostHint(count: number, imageCost: number | undefined): string | undefined {
  const total = imageRequestCloverCost(count, imageCost);
  if (total === undefined || imageCost === undefined) return undefined;
  const totalText = `무료 생성 횟수가 모자라면 클로버 ${total.toLocaleString()}개`;
  return count > 1 ? `${totalText} · 장당 ${imageCost.toLocaleString()}개` : totalText;
}
