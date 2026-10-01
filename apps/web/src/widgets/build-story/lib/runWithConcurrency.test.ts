import { describe, expect, it } from "vitest";

import { runWithConcurrency } from "./runWithConcurrency";

describe("runWithConcurrency", () => {
  it("never runs more than the limit at once and still runs every item", async () => {
    let running = 0;
    let peak = 0;
    const seen: number[] = [];

    await runWithConcurrency([1, 2, 3, 4, 5], 2, async (item) => {
      running += 1;
      peak = Math.max(peak, running);
      await new Promise((resolve) => setTimeout(resolve, 5));
      seen.push(item);
      running -= 1;
    });

    expect(peak).toBe(2);
    expect([...seen].sort()).toEqual([1, 2, 3, 4, 5]);
  });

  it("keeps going after a task rejects", async () => {
    const seen: number[] = [];

    await runWithConcurrency([1, 2, 3], 1, (item) => {
      if (item === 1) return Promise.reject(new Error("fail"));
      seen.push(item);
      return Promise.resolve();
    });

    expect(seen).toEqual([2, 3]);
  });
});
