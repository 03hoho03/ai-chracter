import { describe, expect, it } from "vitest";

import { calculateTargetSize } from "./resizeImage";

/** canvas 경로(`resizeImage`)는 `environment: "node"`에 canvas가 없어 테스트하지 않는다. */
describe("calculateTargetSize", () => {
  it("가로형은 너비를 maxEdge로 맞추고 비율을 유지한다", () => {
    expect(calculateTargetSize(4000, 3000, 512)).toEqual({ width: 512, height: 384 });
  });

  it("세로형은 높이를 maxEdge로 맞추고 비율을 유지한다", () => {
    expect(calculateTargetSize(3000, 4000, 512)).toEqual({ width: 384, height: 512 });
  });

  it("정사각형은 양변을 maxEdge로 맞춘다", () => {
    expect(calculateTargetSize(2048, 2048, 512)).toEqual({ width: 512, height: 512 });
  });

  it("이미 maxEdge 이하면 확대하지 않는다", () => {
    expect(calculateTargetSize(300, 200, 512)).toEqual({ width: 300, height: 200 });
  });

  it("정확히 maxEdge면 그대로 둔다", () => {
    expect(calculateTargetSize(512, 256, 512)).toEqual({ width: 512, height: 256 });
  });

  it("극단적인 비율에서도 짧은 변이 0이 되지 않는다", () => {
    expect(calculateTargetSize(10000, 1, 512)).toEqual({ width: 512, height: 1 });
  });
});
