import { describe, expect, it, vi } from "vitest";

import { createSingleFlight } from "./singleFlight";

describe("createSingleFlight", () => {
  it("runs the task once when called twice in the same tick, before any re-render could happen", async () => {
    const runExclusive = createSingleFlight();
    const task = vi.fn(async () => "done");
    const [first, second] = await Promise.all([runExclusive(task), runExclusive(task)]);
    expect(task).toHaveBeenCalledTimes(1);
    expect(first).toBe("done");
    expect(second).toBeUndefined();
  });

  it("runs again once the previous task has settled, even if it failed", async () => {
    const runExclusive = createSingleFlight();
    await expect(runExclusive(async () => Promise.reject(new Error("x")))).rejects.toThrow("x");
    const task = vi.fn(async () => 1);
    await runExclusive(task);
    expect(task).toHaveBeenCalledTimes(1);
  });
});
