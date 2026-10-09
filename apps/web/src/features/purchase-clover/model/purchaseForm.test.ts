import { describe, expect, it } from "vitest";

import { purchaseFormSchema, toPortOneCustomer, type PurchaseFormValues } from "./purchaseForm";

const VALID: PurchaseFormValues = {
  payMethodKey: "CARD",
  fullName: "홍길동",
  phoneNumber: "010-1234-5678",
  email: "buyer@example.com",
  agreed: true,
};

function errorPaths(values: PurchaseFormValues): string[] {
  const result = purchaseFormSchema.safeParse(values);
  return result.success ? [] : result.error.issues.map((issue) => issue.path.join("."));
}

describe("purchaseFormSchema", () => {
  it("다 채우고 동의하면 통과한다", () => {
    expect(errorPaths(VALID)).toEqual([]);
  });

  it.each([
    ["이름이 비었다", { fullName: "" }, "fullName"],
    ["이름이 공백뿐이다", { fullName: "   " }, "fullName"],
    ["휴대폰이 9자리다", { phoneNumber: "010123456" }, "phoneNumber"],
    ["휴대폰이 12자리다", { phoneNumber: "010123456789" }, "phoneNumber"],
    ["휴대폰에 글자가 섞였다", { phoneNumber: "010-abcd-5678" }, "phoneNumber"],
    ["이메일 형식이 아니다", { email: "buyer" }, "email"],
    ["유료 조건에 동의하지 않았다", { agreed: false }, "agreed"],
    ["결제수단이 없다", { payMethodKey: "" }, "payMethodKey"],
  ])("%s → 그 칸만 막는다", (_, patch, path) => {
    expect(errorPaths({ ...VALID, ...patch })).toEqual([path]);
  });

  it("휴대폰은 하이픈 없이 10자리도 받는다", () => {
    expect(errorPaths({ ...VALID, phoneNumber: "0111234567" })).toEqual([]);
  });
});

describe("toPortOneCustomer", () => {
  it("결제창에는 이름 앞뒤 공백을 빼고 휴대폰은 숫자만 넘긴다", () => {
    expect(toPortOneCustomer({ ...VALID, fullName: " 홍길동 ", phoneNumber: "010-1234 5678" })).toEqual({
      fullName: "홍길동",
      phoneNumber: "01012345678",
      email: "buyer@example.com",
    });
  });

  // 결제창으로만 가는 값이라 동의·결제수단 같은 폼 필드가 섞이면 안 된다.
  it("구매자 세 칸만 담는다", () => {
    expect(Object.keys(toPortOneCustomer(VALID)).sort()).toEqual(["email", "fullName", "phoneNumber"]);
  });
});
