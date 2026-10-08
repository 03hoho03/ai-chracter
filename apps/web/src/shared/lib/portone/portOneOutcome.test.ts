import { describe, expect, it } from "vitest";

import { classifyPortOneOutcome } from "./portOneOutcome";

describe("classifyPortOneOutcome", () => {
  it("code 없는 값은 성공이다", () => {
    expect(classifyPortOneOutcome({ type: "returned", response: { code: undefined } })).toBe("succeeded");
    expect(classifyPortOneOutcome({ type: "returned", response: {} })).toBe("succeeded");
  });

  // SDK 는 실패·취소를 던지지 않고 값의 code 로 준다 — code 를 보지 않으면 취소한 결제를 서버에 확정하러 간다.
  it("code 가 있으면 완료되지 않은 것이다(취소와 거절을 가르지 않는다)", () => {
    expect(classifyPortOneOutcome({ type: "returned", response: { code: "FAILURE_TYPE_PG" } })).toBe("notCompleted");
  });

  it("값이 없으면 리다이렉트로 페이지를 떠난 것이다", () => {
    expect(classifyPortOneOutcome({ type: "returned", response: undefined })).toBe("redirecting");
  });

  it("포트원 오류가 던져지면 요청이 거절된 것이다", () => {
    expect(classifyPortOneOutcome({ type: "threw", isPortOneError: true })).toBe("failed");
  });

  // 로더가 실패한 시도를 기억해 다시 눌러도 같다 — 새로고침 안내로 가야 한다.
  it("포트원 오류가 아닌 것이 던져지면 SDK 를 못 불러온 것이다", () => {
    expect(classifyPortOneOutcome({ type: "threw", isPortOneError: false })).toBe("sdkUnavailable");
  });
});
