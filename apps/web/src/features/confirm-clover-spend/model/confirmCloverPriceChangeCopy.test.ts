import { describe, expect, it } from "vitest";

import { cloverPriceChangeCopy } from "./confirmCloverPriceChangeCopy";

describe("가격 바뀜 확인 문구", () => {
  it("채팅은 새 가격의 클로버 수와 보내기를 말한다", () => {
    expect(cloverPriceChangeCopy("chat", 60)).toEqual({
      description: "지금 가격으로는 클로버 60개가 차감돼요. 이대로 보낼까요?",
      confirmLabel: "새 가격으로 보내기",
    });
  });

  it("이미지는 요청 전체 금액과 만들기를 말한다", () => {
    expect(cloverPriceChangeCopy("image", 1200)).toEqual({
      description: "지금 가격으로는 클로버 1,200개가 차감돼요. 이대로 만들까요?",
      confirmLabel: "새 가격으로 만들기",
    });
  });

  it("금액을 모르면 숫자 없이 묻는다", () => {
    expect(cloverPriceChangeCopy("chat", undefined).description).toBe(
      "바뀐 가격으로 클로버가 차감돼요. 이대로 보낼까요?",
    );
  });
});
