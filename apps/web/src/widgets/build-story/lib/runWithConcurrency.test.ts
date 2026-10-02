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

  it("starts no more items once the signal aborts, but lets the running ones finish", async () => {
    const controller = new AbortController();
    const started: number[] = [];
    const finished: number[] = [];

    await runWithConcurrency(
      [1, 2, 3, 4, 5],
      2,
      async (item) => {
        started.push(item);
        if (item === 2) controller.abort();
        await new Promise((resolve) => setTimeout(resolve, 5));
        finished.push(item);
      },
      controller.signal,
    );

    expect(started).toEqual([1, 2]);
    expect([...finished].sort()).toEqual([1, 2]);
  });

  it("starts nothing when the signal has already aborted", async () => {
    const started: number[] = [];

    await runWithConcurrency(
      [1, 2],
      2,
      (item) => {
        started.push(item);
        return Promise.resolve();
      },
      AbortSignal.abort(),
    );

    expect(started).toEqual([]);
  });
});
