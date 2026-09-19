import { describe, expect, it } from "vitest";

import { isCloverSpendConfirmRequired } from "./cloverSpendConfirm";

/** clover-goal-prompt.md CL-19 — 이 판정이 틀리면 둘 중 하나가 난다: 동의를 물어야 할 때
 * 안 묻거나(무단 차감), 물을 필요 없을 때 묻거나(매 요청 모달). 두 방향을 다 고정한다. */
describe("isCloverSpendConfirmRequired", () => {
  it("CLOVER_CONFIRM_REQUIRED면 참이다 (채팅)", () => {
    expect(
      isCloverSpendConfirmRequired({
        status: 429,
        detail: { code: "CLOVER_CONFIRM_REQUIRED", retryAfterSeconds: 3600, window: "clover" },
        message: "x",
      }),
    ).toBe(true);
  });

  // 채팅·이미지가 **같은 코드**를 쓴다는 것이 표면별 투영을 안 만든 근거다 — 확인 상태가
  // `users` 컬럼 하나라 동의도 하나다. `window`로 판정했다면 이 케이스가 빨개진다.
  it("CLOVER_CONFIRM_REQUIRED면 참이다 (이미지 — window가 다르다)", () => {
    expect(
      isCloverSpendConfirmRequired({
        status: 429,
        detail: { code: "CLOVER_CONFIRM_REQUIRED", retryAfterSeconds: 120, window: "image" },
        message: "x",
      }),
    ).toBe(true);
  });

  // 🔴 부족과 섞이면 안 된다. 저쪽은 배너로 끝나는데 여기서 참을 돌려주면 **잔액이 0인
  // 사용자에게 "계속하기" 모달**이 뜨고, 동의해도 다시 부족으로 막힌다.
  it("CLOVER_REQUIRED(부족)는 거짓이다 — 같은 window라도 code로 갈린다", () => {
    expect(
      isCloverSpendConfirmRequired({
        status: 429,
        detail: { code: "CLOVER_REQUIRED", retryAfterSeconds: 3600, window: "clover" },
        message: "x",
      }),
    ).toBe(false);
  });

  it("다른 429(USER_LIMIT)는 거짓이다", () => {
    expect(
      isCloverSpendConfirmRequired({
        status: 429,
        detail: { code: "USER_LIMIT", retryAfterSeconds: 42, window: "minute" },
        message: "x",
      }),
    ).toBe(false);
  });

  it("429가 아니면 거짓이다", () => {
    expect(isCloverSpendConfirmRequired({ status: 500, detail: null, message: "x" })).toBe(false);
  });
});
