import { describe, expect, it } from "vitest";

import { describeTokenBar } from "./tokenBar";

function tokens(overrides: Partial<Parameters<typeof describeTokenBar>[0]> = {}) {
  return { newInputTokens: 228, cachedTokens: 16980, cacheWriteTokens: 1204, outputTokens: 612, ...overrides };
}

describe("describeTokenBar", () => {
  it("새 입력이 비어 있으면(입력 토큰이 기록되지 않은 호출) 막대를 그리지 않는다", () => {
    expect(describeTokenBar(tokens({ newInputTokens: null }))).toEqual({ kind: "missing" });
  });

  it("캐시 읽기·캐시 쓰기·새 입력·출력 순으로, 새 입력은 측정 서버가 낸 값 그대로", () => {
    const bar = describeTokenBar(tokens());

    expect(bar.kind).toBe("bar");
    if (bar.kind !== "bar") return;
    expect(bar.segments.map((segment) => [segment.part, segment.tokens])).toEqual([
      ["cacheRead", 16980],
      ["cacheWrite", 1204],
      ["newInput", 228],
      ["output", 612],
    ]);
    expect(bar.total).toBe(16980 + 1204 + 228 + 612);
    const ratioSum = bar.segments.reduce((sum, segment) => sum + segment.ratio, 0);
    expect(ratioSum).toBeCloseTo(1, 10);
    expect(bar.segments[0]?.ratio).toBeCloseTo(16980 / 19024, 10);
  });

  it("새 입력을 캐시 칸에서 다시 셈하지 않는다 — 캐시 합이 새 입력보다 커도 서버 값을 쓴다", () => {
    const bar = describeTokenBar(tokens({ newInputTokens: 5, cachedTokens: 900, cacheWriteTokens: 300 }));

    if (bar.kind !== "bar") throw new Error("막대여야 한다");
    expect(bar.segments.find((segment) => segment.part === "newInput")?.tokens).toBe(5);
  });

  it("기록 없는 칸은 길이 0 이고 토큰 수도 비워 둔다 — 0 토큰과 갈린다", () => {
    const bar = describeTokenBar(tokens({ cachedTokens: null, outputTokens: null }));

    if (bar.kind !== "bar") throw new Error("막대여야 한다");
    expect(bar.segments.find((segment) => segment.part === "cacheRead")).toEqual({
      part: "cacheRead",
      tokens: undefined,
      ratio: 0,
    });
    expect(bar.segments.find((segment) => segment.part === "newInput")?.tokens).toBe(228);
    expect(bar.segments.find((segment) => segment.part === "output")?.tokens).toBeUndefined();
    expect(bar.total).toBe(1204 + 228);
  });

  it("토큰이 모두 0 이면 막대 길이도 모두 0 이다(나눗셈이 NaN 이 되지 않는다)", () => {
    const bar = describeTokenBar({ newInputTokens: 0, cachedTokens: 0, cacheWriteTokens: 0, outputTokens: 0 });

    if (bar.kind !== "bar") throw new Error("막대여야 한다");
    expect(bar.segments.map((segment) => segment.ratio)).toEqual([0, 0, 0, 0]);
    expect(bar.segments.map((segment) => segment.tokens)).toEqual([0, 0, 0, 0]);
  });
});
