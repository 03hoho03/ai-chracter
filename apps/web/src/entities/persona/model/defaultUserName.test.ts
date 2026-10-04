import { describe, expect, it } from "vitest";

import { defaultUserNameIssue } from "./defaultUserName";
import { PERSONA_NAME_MAX_LENGTH } from "./persona";

describe("defaultUserNameIssue", () => {
  it("accepts an empty name — the screen falls back to the default word", () => {
    expect(defaultUserNameIssue("")).toBeNull();
    expect(defaultUserNameIssue("   ")).toBeNull();
  });

  it("measures the length after trimming, like the server", () => {
    expect(defaultUserNameIssue(` ${"가".repeat(PERSONA_NAME_MAX_LENGTH)} `)).toBeNull();
    expect(defaultUserNameIssue("가".repeat(PERSONA_NAME_MAX_LENGTH + 1))).toMatch(/이내로/);
  });

  it.each(["{{user}}", "조{수", "별*", "김:민", "- 민"])("rejects %s", (name) => {
    expect(defaultUserNameIssue(name)).not.toBeNull();
  });

  it("checks the trimmed name, so surrounding spaces do not trip the line-start rule", () => {
    expect(defaultUserNameIssue(" 조수 ")).toBeNull();
  });
});
