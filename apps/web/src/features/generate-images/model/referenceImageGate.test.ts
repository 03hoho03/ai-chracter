import { describe, expect, it } from "vitest";

import { isReferenceImageEnabled } from "./referenceImageGate";

// 서버 목록의 모델 id는 지금 `"v1"` 하나뿐인 상수 타입이라, 판정에 쓰는 두 필드만 가진 모양으로 만든다.
function makeModel(id: string, supportsReferenceImage: boolean) {
  return { id, supportsReferenceImage };
}

describe("isReferenceImageEnabled", () => {
  it("고른 모델이 참조를 받으면 켠다", () => {
    expect(isReferenceImageEnabled([makeModel("v1", true)], "v1")).toBe(true);
  });

  // 서버는 이 값을 모델마다 준다 — 다른 모델의 값을 빌려 오면 고른 모델이 못 받는 참조를 싣게 된다.
  it("고른 모델이 참조를 안 받으면 다른 모델이 받아도 끈다", () => {
    expect(isReferenceImageEnabled([makeModel("v1", false), makeModel("v2", true)], "v1")).toBe(false);
  });

  it("고른 모델을 목록에서 못 찾으면 끈다", () => {
    expect(isReferenceImageEnabled([makeModel("v1", true)], "gone")).toBe(false);
  });

  it("목록이 아직 없으면 끈다", () => {
    expect(isReferenceImageEnabled(undefined, "v1")).toBe(false);
  });
});
