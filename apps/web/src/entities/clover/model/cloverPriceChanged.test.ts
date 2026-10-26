import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import {
  allowanceAfterCloverConfirm,
  canAskCloverConfirm,
  FIRST_CLOVER_CONFIRM_ALLOWANCE,
  getCloverPriceChangedCost,
  isCloverPriceChangedError,
} from "./cloverPriceChanged";

const priceChanged = new ApiErrorObject({
  status: 409,
  detail: { code: "CLOVER_PRICE_CHANGED", currentCost: 60 },
  message: "conflict",
});
const confirmRequired = new ApiErrorObject({
  status: 429,
  detail: { code: "CLOVER_CONFIRM_REQUIRED", retryAfterSeconds: 10, window: "clover" },
  message: "limit",
});
const turnInProgress = new ApiErrorObject({
  status: 409,
  detail: { code: "CHAT_TURN_IN_PROGRESS" },
  message: "conflict",
});

describe("가격 바뀜 거절 판정", () => {
  it("가격 바뀜 409 를 알아보고 지금 금액을 읽는다", () => {
    expect(isCloverPriceChangedError(priceChanged)).toBe(true);
    expect(getCloverPriceChangedCost(priceChanged)).toBe(60);
  });

  it("같은 409 라도 다른 코드는 가격 바뀜이 아니다", () => {
    expect(isCloverPriceChangedError(turnInProgress)).toBe(false);
    expect(getCloverPriceChangedCost(turnInProgress)).toBeUndefined();
  });

  it("지금 금액이 숫자가 아니면 금액 없이 가격 바뀜으로 본다", () => {
    const noCost = new ApiErrorObject({ status: 409, detail: { code: "CLOVER_PRICE_CHANGED" }, message: "conflict" });
    expect(isCloverPriceChangedError(noCost)).toBe(true);
    expect(getCloverPriceChangedCost(noCost)).toBeUndefined();
  });
});

describe("확인 뒤 다시 보내는 요청이 또 물을 수 있는 것", () => {
  it("처음 요청은 가격 바뀜도 하루 한 번 확인도 묻는다", () => {
    expect(canAskCloverConfirm(priceChanged, FIRST_CLOVER_CONFIRM_ALLOWANCE)).toBe(true);
    expect(canAskCloverConfirm(confirmRequired, FIRST_CLOVER_CONFIRM_ALLOWANCE)).toBe(true);
  });

  it("가격 바뀜을 확인한 뒤에는 가격 바뀜을 다시 묻지 않지만 하루 한 번 확인은 묻는다", () => {
    const next = allowanceAfterCloverConfirm(priceChanged, FIRST_CLOVER_CONFIRM_ALLOWANCE);
    expect(canAskCloverConfirm(priceChanged, next)).toBe(false);
    expect(canAskCloverConfirm(confirmRequired, next)).toBe(true);
  });

  it("하루 한 번 확인을 한 뒤에는 아무것도 다시 묻지 않는다", () => {
    const afterPrice = allowanceAfterCloverConfirm(priceChanged, FIRST_CLOVER_CONFIRM_ALLOWANCE);
    const next = allowanceAfterCloverConfirm(confirmRequired, afterPrice);
    expect(canAskCloverConfirm(priceChanged, next)).toBe(false);
    expect(canAskCloverConfirm(confirmRequired, next)).toBe(false);
  });
});
