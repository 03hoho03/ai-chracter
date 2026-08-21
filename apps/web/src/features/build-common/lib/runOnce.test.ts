import { describe, expect, it, vi } from "vitest";

import { runOnce } from "./runOnce";

describe("runOnce", () => {
  it("runs once and shares the result across later calls", async () => {
    const run = vi.fn(() => Promise.resolve("draft-1"));
    const once = runOnce(run);

    await expect(once()).resolves.toBe("draft-1");
    await expect(once()).resolves.toBe("draft-1");
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("runs once when calls overlap before the first one settles", async () => {
    let resolveRun: (value: string) => void = () => undefined;
    const run = vi.fn(() => new Promise<string>((resolve) => (resolveRun = resolve)));
    const once = runOnce(run);

    const [first, second] = [once(), once()];
    resolveRun("draft-1");

    expect(await Promise.all([first, second])).toEqual(["draft-1", "draft-1"]);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("retries on the next call after a failure", async () => {
    const run = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new Error("네트워크 오류"))
      .mockResolvedValueOnce("draft-1");
    const once = runOnce(run);

    await expect(once()).rejects.toThrow("네트워크 오류");
    await expect(once()).resolves.toBe("draft-1");
    expect(run).toHaveBeenCalledTimes(2);
  });
});
