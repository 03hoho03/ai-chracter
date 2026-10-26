import { z } from "zod";

import { isApiError } from "@/shared/api/client";

/** 서버가 클로버를 깎기 직전에 요청의 가격 버전을 대조해, 화면이 본 가격표가 옛 것이면 내는 409 의 본문. 지금 금액
 * (`currentCost`)은 그 요청의 총액이다 — 채팅은 턴 가격, 이미지는 장수 × 장당 가격. 새 가격 버전은 싣지 않으므로 화면은
 * 가격표를 다시 받아야 한다. 이 본문은 HTTP 오류 응답이라 코드젠을 타지 않는다(서버 `core/rate_limit_gate.py` 의
 * `_check_price_version` 과 손으로 맞춘 사본). 금액이 숫자가 아니어도 코드만 맞으면 가격 바뀜으로 본다 — 금액 없이 묻는다. */
const priceChangedDetailSchema = z.object({
  code: z.literal("CLOVER_PRICE_CHANGED"),
  currentCost: z.number().optional().catch(undefined),
});

function parsePriceChanged(error: unknown) {
  if (!isApiError(error) || error.status !== 409) return undefined;
  const parsed = priceChangedDetailSchema.safeParse(error.detail);
  return parsed.success ? parsed.data : undefined;
}

export function isCloverPriceChangedError(error: unknown): boolean {
  return parsePriceChanged(error) !== undefined;
}

export function getCloverPriceChangedCost(error: unknown): number | undefined {
  return parsePriceChanged(error)?.currentCost;
}

/** 한 번의 사용자 조작이 다시 보내는 요청에서 무엇을 또 물을 수 있는가 — 확인 모달의 무한 왕복을 막는 차단기다.
 *
 * 둘을 한 불리언으로 묶지 않는 이유: 서버는 가격 버전을 하루 한 번 확인보다 먼저 대조한다. 그래서 가격 바뀜을 확인하고
 * 다시 보낸 요청이 이어서 하루 한 번 확인을 받는 것은 정상 흐름이고, 그 확인은 띄워야 한다. 같은 확인을 두 번 묻는 것만
 * 막는다. 하루 한 번 확인 뒤에는 가격 바뀜도 다시 묻지 않는다 — 그 사이 가격이 또 바뀐 드문 경우는 평소의 오류로 끝난다. */
export type CloverConfirmAllowance = { readonly spend: boolean; readonly priceChange: boolean };

export const FIRST_CLOVER_CONFIRM_ALLOWANCE: CloverConfirmAllowance = { spend: true, priceChange: true };

export function canAskCloverConfirm(error: unknown, allowance: CloverConfirmAllowance): boolean {
  return isCloverPriceChangedError(error) ? allowance.priceChange : allowance.spend;
}

export function allowanceAfterCloverConfirm(error: unknown, allowance: CloverConfirmAllowance): CloverConfirmAllowance {
  return isCloverPriceChangedError(error) ? { ...allowance, priceChange: false } : { spend: false, priceChange: false };
}
