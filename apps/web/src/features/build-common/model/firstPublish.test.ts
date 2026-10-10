import { describe, expect, it } from "vitest";

import { FIRST_PUBLISH_VISIBILITY_RESULT, needsFirstPublishConfirm } from "./firstPublish";

describe("needsFirstPublishConfirm", () => {
  it("발행된 버전이 없으면 묻는다", () => {
    expect(needsFirstPublishConfirm(0)).toBe(true);
  });

  it("이력을 확인하지 못했으면 묻는다", () => {
    expect(needsFirstPublishConfirm(undefined)).toBe(true);
  });

  it.each([1, 3])("발행된 버전이 %i개면 묻지 않고 곧장 발행한다", (count) => {
    expect(needsFirstPublishConfirm(count)).toBe(false);
  });
});

describe("FIRST_PUBLISH_VISIBILITY_RESULT", () => {
  // 발행 취소 API 는 없지만 공개범위는 발행 뒤에도 바꿀 수 있어, 되돌릴 수 없다는 말은 공개 여부에 대해 거짓이다.
  it("어느 공개범위에서도 되돌릴 수 없다고 말하지 않는다", () => {
    for (const sentence of Object.values(FIRST_PUBLISH_VISIBILITY_RESULT)) {
      expect(sentence).not.toMatch(/되돌릴 수 없|취소할 수 없/);
    }
  });
});
