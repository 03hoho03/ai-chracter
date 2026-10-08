import { describe, expect, it } from "vitest";

import { mypageSearchSchema } from "./mypageSearch";

describe("mypageSearchSchema", () => {
  it("파라미터가 없으면 부재다", () => {
    expect(mypageSearchSchema.parse({})).toEqual({});
  });

  it("포트원이 붙인 인증 id 와 실패 코드를 읽고 나머지는 버린다", () => {
    expect(
      mypageSearchSchema.parse({ identityVerificationId: "idv1", code: "X", message: "m", transactionType: "t" }),
    ).toEqual({ identityVerificationId: "idv1", code: "X" });
  });

  it("숫자로 온 실패 코드도 버리지 않고 문자열로 읽는다", () => {
    expect(mypageSearchSchema.parse({ identityVerificationId: "idv1", code: 2001 })).toEqual({
      identityVerificationId: "idv1",
      code: "2001",
    });
  });
});
