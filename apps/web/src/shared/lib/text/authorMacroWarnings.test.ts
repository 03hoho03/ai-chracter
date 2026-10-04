import { describe, expect, it } from "vitest";

import { expandAuthorMacros } from "./authorMacros";
import { findAuthorMacroTypos, hasCharMacro, hasUserMacro } from "./authorMacroWarnings";

const NAMES = { userName: "지훈", charName: "유나" };

describe("findAuthorMacroTypos", () => {
  it.each([
    ["{user}가 웃는다", ["{user}"]],
    ["{char} 와 {CHAR}", ["{char}", "{CHAR}"]],
    ["{{user}가 웃는다", ["{{user}"]],
    ["{user}}가 웃는다", ["{user}}"]],
    ["{{{user}}}", ["{{{user}}}"]],
    ["{{user 문을 연다", ["{{user"]],
    ["<USER> 와 <char>", ["<USER>", "<char>"]],
    ["{user} 그리고 또 {user}", ["{user}"]],
  ])("%s", (text, expected) => {
    expect(findAuthorMacroTypos(text)).toEqual(expected);
  });

  it.each([
    "{{user}}가 웃는다",
    "{{ user }}·{{\tchar\t}}",
    "{{USER}}",
    "{username} 같은 다른 낱말",
    "{{img::도희/기획 회의}}",
    "user 와 char 는 그냥 글자",
    "",
  ])("leaves %s alone", (text) => {
    expect(findAuthorMacroTypos(text)).toEqual([]);
  });

  // 오타로 알린 모양은 실제로 이름으로 바뀌지 않아야 한다 — 바뀌는 모양을 오타라 하면 작가가 맞는 글을 고친다.
  it("flags only shapes the expander leaves as written", () => {
    for (const typo of ["{user}", "{{user}", "{user}}", "{{user", "<USER>"]) {
      expect(expandAuthorMacros(typo, NAMES)).toBe(typo);
    }
  });
});

describe("hasCharMacro / hasUserMacro", () => {
  it("finds macros the expander replaces", () => {
    expect(hasCharMacro("{{ Char }}가 손을 흔든다")).toBe(true);
    expect(hasUserMacro("{{user}}의 자리")).toBe(true);
  });

  it("ignores typos and the other macro", () => {
    expect(hasCharMacro("{char} 와 {{user}}")).toBe(false);
    expect(hasUserMacro("{user} 와 {{char}}")).toBe(false);
  });
});
