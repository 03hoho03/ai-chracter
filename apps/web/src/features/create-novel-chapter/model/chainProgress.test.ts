import { describe, expect, it } from "vitest";

import { toChainProgress, toChainRunningText } from "./chainProgress";

describe("toChainProgress", () => {
  it("reads completed / planned batches of the parent job", () => {
    expect(toChainProgress({ completedBatches: 1, plannedBatches: 3 })).toEqual({ completed: 1, planned: 3 });
  });

  it("has no progress before the server fixes the batch count or without a job", () => {
    expect(toChainProgress({ completedBatches: null, plannedBatches: 3 })).toBeUndefined();
    expect(toChainProgress({ completedBatches: 0, plannedBatches: null })).toBeUndefined();
    expect(toChainProgress(null)).toBeUndefined();
  });
});

describe("toChainRunningText", () => {
  it("adds the batch count when known", () => {
    expect(toChainRunningText({ completed: 1, planned: 3 })).toBe("남은 대화를 소설로 쓰고 있어요 · 묶음 1/3.");
    expect(toChainRunningText(undefined)).toBe("남은 대화를 소설로 쓰고 있어요.");
  });
});
