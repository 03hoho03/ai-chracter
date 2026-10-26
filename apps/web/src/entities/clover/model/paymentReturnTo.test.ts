import { describe, expect, it } from "vitest";

import { clearPaymentReturnTo, readPaymentReturnTo, rememberPaymentReturnTo } from "./paymentReturnTo";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
    values,
  };
}

const blocked = () => {
  throw new DOMException("The operation is insecure.", "SecurityError");
};

describe("결제창 왕복의 복귀 주소", () => {
  it("결제창을 띄우기 전에 둔 값을 돌아와서 읽고, 지우면 사라진다", () => {
    const storage = memoryStorage();
    rememberPaymentReturnTo("/chat/room-1", () => storage);
    expect(readPaymentReturnTo(() => storage)).toBe("/chat/room-1");
    clearPaymentReturnTo(() => storage);
    expect(readPaymentReturnTo(() => storage)).toBeUndefined();
  });

  // 앞 결제의 복귀 주소가 다음 결제(복귀 주소 없이 연 충전)에 붙으면 엉뚱한 곳으로 "돌아가기"를 둔다.
  it("복귀 주소 없이 결제하면 앞 결제의 값을 지운다", () => {
    const storage = memoryStorage();
    rememberPaymentReturnTo("/chat/room-1", () => storage);
    rememberPaymentReturnTo(undefined, () => storage);
    expect(storage.values.size).toBe(0);
  });

  it("키는 하나다", () => {
    const storage = memoryStorage();
    rememberPaymentReturnTo("/chat/a", () => storage);
    rememberPaymentReturnTo("/chat/b", () => storage);
    expect([...storage.values.keys()]).toEqual(["ttona.cloverReturnTo"]);
  });

  it("저장소가 막혀도 던지지 않는다", () => {
    expect(() => rememberPaymentReturnTo("/chat/a", blocked)).not.toThrow();
    expect(readPaymentReturnTo(blocked)).toBeUndefined();
    expect(() => clearPaymentReturnTo(blocked)).not.toThrow();
  });
});
