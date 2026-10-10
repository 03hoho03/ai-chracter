import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import { payoutInfoSchema, type PayoutInfoFormValues } from "./schema";

const VALID = {
  legalName: "홍길동",
  rrn: "900101-1234567",
  bankCode: "004",
  accountNumber: "123-456-789012",
  agreed: true,
} as const satisfies PayoutInfoFormValues;

function errorPaths(values: PayoutInfoFormValues): string[] {
  const result = payoutInfoSchema.safeParse(values);
  return result.success ? [] : result.error.issues.map((issue) => issue.path.join("."));
}

describe("payoutInfoSchema", () => {
  it("하이픈을 넣어 적은 주민등록번호·계좌번호를 받는다", () => {
    expect(errorPaths(VALID)).toEqual([]);
  });

  it.each([
    ["공백뿐인 실명", { legalName: "   " }, "legalName"],
    ["41자 실명", { legalName: "가".repeat(41) }, "legalName"],
    ["12자리 주민등록번호", { rrn: "900101-123456" }, "rrn"],
    ["숫자가 아닌 주민등록번호", { rrn: "900101-12345a7" }, "rrn"],
    ["고르지 않은 은행", { bankCode: null }, "bankCode"],
    ["목록 밖 은행", { bankCode: "999" }, "bankCode"],
    ["5자리 계좌번호", { accountNumber: "12345" }, "accountNumber"],
    ["21자리 계좌번호", { accountNumber: "1".repeat(21) }, "accountNumber"],
    ["동의하지 않음", { agreed: false }, "agreed"],
  ])("%s 는 그 칸의 오류다", (_name, override, path) => {
    expect(errorPaths({ ...VALID, ...override })).toEqual([path]);
  });

  // 서버와 같은 경계 — 앞뒤 공백을 뺀 40자, 계좌 6·20자리는 받는다.
  it("경계 값은 받는다", () => {
    expect(errorPaths({ ...VALID, legalName: ` ${"가".repeat(40)} ` })).toEqual([]);
    expect(errorPaths({ ...VALID, accountNumber: "123456" })).toEqual([]);
    expect(errorPaths({ ...VALID, accountNumber: "1".repeat(20) })).toEqual([]);
  });
});

describe("formToServer", () => {
  it("실명 앞뒤 공백과 숫자 칸의 하이픈·공백을 뺀다", () => {
    expect(formToServer({ ...VALID, legalName: " 홍길동 ", accountNumber: "123 456-789012" })).toEqual({
      legalName: "홍길동",
      rrn: "9001011234567",
      bankCode: "004",
      accountNumber: "123456789012",
      agreed: true,
    });
  });
});
