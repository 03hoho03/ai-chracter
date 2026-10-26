import { describe, expect, it } from "vitest";

import { getProductsFootnote } from "./productsFootnote";

describe("getProductsFootnote", () => {
  it("비로그인에게는 로그인한 뒤 결제로 이어진다고 말한다", () => {
    expect(getProductsFootnote("guest")).toEqual({
      text: "상품을 고르면 로그인한 뒤 그 상품의 결제로 이어져요.",
      isWideOnly: false,
    });
  });

  it("결제가 꺼져 있으면 준비 중이라고 말한다", () => {
    expect(getProductsFootnote("disabled")).toEqual({ text: "클로버 결제는 아직 준비 중이에요.", isWideOnly: false });
  });

  // 넓은 화면에서는 이유를 말하는 구매 조건이 옆 열에 있어, 누를 수 없는 행 아래에서 이유가 바로 읽히지 않는다.
  // 좁은 화면에서는 구매 조건이 바로 위라 되풀이하지 않는다.
  it("본인인증 전이면 넓은 화면에서만 이유를 덧붙인다", () => {
    expect(getProductsFootnote("identityRequired")).toEqual({
      text: "본인인증을 마치면 살 수 있어요.",
      isWideOnly: true,
    });
  });

  it("만 19세 미만이면 넓은 화면에서만 나이 조건을 덧붙인다", () => {
    expect(getProductsFootnote("ageRestricted")).toEqual({
      text: "클로버는 만 19세 이상만 구매할 수 있어요.",
      isWideOnly: true,
    });
  });

  it.each(["products", "pending"] as const)("%s 이면 덧붙이지 않는다", (section) => {
    expect(getProductsFootnote(section)).toBeNull();
  });
});
