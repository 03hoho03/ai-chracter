import { describe, expect, it } from "vitest";

import { triggerKeywordError } from "./keywordNoteEdit";

describe("triggerKeywordError", () => {
  it("accepts a new keyword within the limits", () => {
    expect(triggerKeywordError("은빛열쇠", ["밤"])).toBeUndefined();
    expect(triggerKeywordError("가".repeat(20), [])).toBeUndefined();
  });

  it("refuses a keyword longer than 20 characters with a reason", () => {
    expect(triggerKeywordError("가".repeat(21), [])).toMatch(/20자/);
  });

  it("refuses an 11th keyword with a reason", () => {
    const ten = Array.from({ length: 10 }, (_, i) => `키워드${i}`);

    expect(triggerKeywordError("새 키워드", ten)).toMatch(/10개/);
  });

  it("refuses a keyword that matches an existing one after case and Unicode folding", () => {
    expect(triggerKeywordError("usb", ["USB"])).toBeDefined();
    expect(triggerKeywordError("한밤".normalize("NFD"), ["한밤"])).toBeDefined();
  });

  it("refuses a blank keyword", () => {
    expect(triggerKeywordError("   ", [])).toBeDefined();
  });
});
