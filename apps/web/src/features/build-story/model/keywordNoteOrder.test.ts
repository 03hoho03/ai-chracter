import { describe, expect, it } from "vitest";

import { dragMoveIndices, stepMoveIndices } from "./keywordNoteOrder";

describe("dragMoveIndices", () => {
  const ids = ["a", "b", "c"];

  it("moves the dragged note to the position of the note it was dropped on", () => {
    expect(dragMoveIndices(ids, "c", "a")).toEqual({ from: 2, to: 0 });
    expect(dragMoveIndices(ids, "a", "b")).toEqual({ from: 0, to: 1 });
  });

  it("does nothing when dropped on itself, outside the list, or with an unknown id", () => {
    expect(dragMoveIndices(ids, "b", "b")).toBeUndefined();
    expect(dragMoveIndices(ids, "b", null)).toBeUndefined();
    expect(dragMoveIndices(ids, "x", "a")).toBeUndefined();
    expect(dragMoveIndices(ids, "a", "x")).toBeUndefined();
  });
});

describe("stepMoveIndices", () => {
  it("moves one place up or down", () => {
    expect(stepMoveIndices(1, -1, 3)).toEqual({ from: 1, to: 0 });
    expect(stepMoveIndices(1, 1, 3)).toEqual({ from: 1, to: 2 });
  });

  it("does nothing past either end", () => {
    expect(stepMoveIndices(0, -1, 3)).toBeUndefined();
    expect(stepMoveIndices(2, 1, 3)).toBeUndefined();
  });
});
