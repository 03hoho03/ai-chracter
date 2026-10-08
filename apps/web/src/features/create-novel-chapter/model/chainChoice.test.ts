import { describe, expect, it } from "vitest";

import type { NovelChainEstimate } from "@/entities/novel";

import { CHAIN_CHOICE_VALUE, toChainChoice, toSelectionAfterModelChange } from "./chainChoice";

const estimates: NovelChainEstimate[] = [
  { model: "gemini", name: "기본", batchCount: 3, maxEpisodeCount: 9, cost: 270 },
  { model: "opus", name: "상위", batchCount: 1, maxEpisodeCount: 4, cost: 400 },
];

const proposal = { candidates: [{ messageId: "a" }, { messageId: "b" }], suggestion: { endMessageId: "b" } };

describe("toChainChoice", () => {
  it("shows the chosen model's estimate when the rest of the chat needs more than one batch", () => {
    expect(toChainChoice(estimates, "gemini")).toEqual(estimates[0]);
  });

  it("hides it when one batch holds the rest (same as picking the last turn), or the model has no estimate", () => {
    expect(toChainChoice(estimates, "opus")).toBeUndefined();
    expect(toChainChoice(estimates, "sonnet")).toBeUndefined();
    expect(toChainChoice(undefined, "gemini")).toBeUndefined();
  });
});

describe("toSelectionAfterModelChange", () => {
  it("keeps the whole-rest choice when the new model still offers it", () => {
    expect(toSelectionAfterModelChange(CHAIN_CHOICE_VALUE, proposal, true)).toBe(CHAIN_CHOICE_VALUE);
  });

  it("falls back to the new suggestion when the new model no longer offers it", () => {
    expect(toSelectionAfterModelChange(CHAIN_CHOICE_VALUE, proposal, false)).toBe("b");
  });

  it("follows the turn rules for a picked turn", () => {
    expect(toSelectionAfterModelChange("a", proposal, true)).toBe("a");
    expect(toSelectionAfterModelChange("z", proposal, true)).toBe("b");
  });
});
