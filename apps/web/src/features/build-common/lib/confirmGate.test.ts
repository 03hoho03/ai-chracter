import { describe, expect, it, vi } from "vitest";

import { createConfirmGate } from "./confirmGate";

const neverSettles = () => new Promise<boolean>(() => undefined);

describe("createConfirmGate", () => {
  it("passes the answer through", async () => {
    const gate = createConfirmGate();

    await expect(gate(() => Promise.resolve(true))).resolves.toBe(true);
    await expect(gate(() => Promise.resolve(false))).resolves.toBe(false);
  });

  it("drops a second request while the first is still waiting, without asking", async () => {
    let answer: (value: boolean) => void = () => undefined;
    const gate = createConfirmGate();
    const second = vi.fn(() => Promise.resolve(true));

    const first = gate(() => new Promise<boolean>((resolve) => (answer = resolve)));
    await expect(gate(second)).resolves.toBe(false);
    expect(second).not.toHaveBeenCalled();

    answer(true);
    await expect(first).resolves.toBe(true);
  });

  it("opens again after the request settles, including a failed one", async () => {
    const gate = createConfirmGate();

    await expect(gate(() => Promise.reject(new Error("조회 실패")))).rejects.toThrow("조회 실패");
    await expect(gate(() => Promise.resolve(true))).resolves.toBe(true);
  });

  it("does not block a new gate when an earlier gate's answer was dropped and never arrives", async () => {
    const leftScreen = createConfirmGate();
    void leftScreen(neverSettles);

    const nextScreen = createConfirmGate();
    await expect(nextScreen(() => Promise.resolve(true))).resolves.toBe(true);
  });
});
