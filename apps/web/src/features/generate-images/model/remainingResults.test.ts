import { describe, expect, it } from "vitest";

import { isEveryResultHidden } from "./remainingResults";

const TWO_IMAGES = [{ assetId: "a" }, { assetId: "b" }];
const BASE = { requestedCount: 2, hasPollError: false };

describe("isEveryResultHidden", () => {
  it("완료된 결과를 모두 지웠으면 참이다", () => {
    expect(
      isEveryResultHidden({ ...BASE, job: { status: "succeeded", images: TWO_IMAGES }, hiddenAssetIds: new Set(["a", "b"]) }),
    ).toBe(true);
  });

  it("한 장이라도 남았으면 거짓이다(지운 칸은 빈 열로 남는다)", () => {
    expect(
      isEveryResultHidden({ ...BASE, job: { status: "succeeded", images: TWO_IMAGES }, hiddenAssetIds: new Set(["a"]) }),
    ).toBe(false);
  });

  it("부분 차단으로 한 장만 받은 완료를 그 한 장까지 지웠으면 참이다", () => {
    expect(
      isEveryResultHidden({ ...BASE, job: { status: "succeeded", images: [{ assetId: "a" }] }, hiddenAssetIds: new Set(["a"]) }),
    ).toBe(true);
  });

  it("진행 중에 나온 것을 지워도 아직 나올 칸이 남았으면 거짓이다", () => {
    expect(
      isEveryResultHidden({ ...BASE, job: { status: "running", images: [{ assetId: "a" }] }, hiddenAssetIds: new Set(["a"]) }),
    ).toBe(false);
  });

  it("진행 중이라도 요청한 장수가 다 나와 모두 지웠으면 참이다", () => {
    expect(
      isEveryResultHidden({ ...BASE, job: { status: "running", images: TWO_IMAGES }, hiddenAssetIds: new Set(["a", "b"]) }),
    ).toBe(true);
  });

  it("완료 전 폴링 오류면 오류 안내를 남기려고 거짓이다", () => {
    expect(
      isEveryResultHidden({
        ...BASE,
        hasPollError: true,
        job: { status: "running", images: TWO_IMAGES },
        hiddenAssetIds: new Set(["a", "b"]),
      }),
    ).toBe(false);
  });

  it("완료 뒤의 폴링 오류는 판정을 바꾸지 않는다", () => {
    expect(
      isEveryResultHidden({
        ...BASE,
        hasPollError: true,
        job: { status: "succeeded", images: TWO_IMAGES },
        hiddenAssetIds: new Set(["a", "b"]),
      }),
    ).toBe(true);
  });

  it("실패한 잡과 받은 이미지가 없는 잡은 거짓이다", () => {
    expect(
      isEveryResultHidden({ ...BASE, job: { status: "failed", images: TWO_IMAGES }, hiddenAssetIds: new Set(["a", "b"]) }),
    ).toBe(false);
    expect(isEveryResultHidden({ ...BASE, job: { status: "succeeded", images: [] }, hiddenAssetIds: new Set() })).toBe(
      false,
    );
  });
});
