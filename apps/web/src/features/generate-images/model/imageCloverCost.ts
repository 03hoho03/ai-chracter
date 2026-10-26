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
