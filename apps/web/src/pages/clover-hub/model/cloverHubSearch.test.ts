import { describe, expect, it } from "vitest";

import { CLOVER_HUB_SEARCH_SCHEMA } from "./cloverHubSearch";

describe("CLOVER_HUB_SEARCH_SCHEMA", () => {
  it("파라미터가 없으면 부재다", () => {
    expect(CLOVER_HUB_SEARCH_SCHEMA.parse({})).toEqual({});
  });

  it("포트원이 붙인 결제 id 와 실패 코드를 읽고 나머지는 버린다", () => {
    expect(
      CLOVER_HUB_SEARCH_SCHEMA.parse({ paymentId: "pay_1", code: "FAILURE_TYPE_PG", message: "x", txId: "t" }),
    ).toEqual({ paymentId: "pay_1", code: "FAILURE_TYPE_PG" });
  });

  it("주소에 담겨 온 상품 키를 읽는다", () => {
    expect(CLOVER_HUB_SEARCH_SCHEMA.parse({ product: "lite" })).toEqual({ product: "lite" });
  });

  // 문자열이 아닌 상품 값은 어긋난 URL 이다 — 페이지를 죽이지 않고 부재로 접는다.
  it("문자열이 아닌 상품 값은 부재로 읽는다", () => {
    expect(CLOVER_HUB_SEARCH_SCHEMA.parse({ product: 1 })).toEqual({});
  });

  // 라우터가 숫자만인 쿼리 값을 숫자로 준다 — 버리면 실패한 결제가 성공처럼 읽힌다.
  it("숫자로 온 실패 코드도 버리지 않고 문자열로 읽는다", () => {
    expect(CLOVER_HUB_SEARCH_SCHEMA.parse({ paymentId: "pay_1", code: 1001 })).toEqual({
      paymentId: "pay_1",
      code: "1001",
    });
  });
});
