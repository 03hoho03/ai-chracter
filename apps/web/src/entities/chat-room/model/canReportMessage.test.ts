import { describe, expect, it } from "vitest";

import { canReportMessage } from "./canReportMessage";

const SAVED_ID = "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b";

describe("canReportMessage", () => {
  it("allows a saved AI response", () => {
    expect(canReportMessage({ id: SAVED_ID, role: "assistant" })).toBe(true);
  });

  it("rejects a user message even when its id looks saved", () => {
    expect(canReportMessage({ id: SAVED_ID, role: "user" })).toBe(false);
  });

  it("rejects the temporary bubbles the chat screen draws while streaming or after an ending", () => {
    expect(canReportMessage({ id: "streaming", role: "assistant" })).toBe(false);
    expect(canReportMessage({ id: "ending-epilogue", role: "assistant" })).toBe(false);
  });
});
