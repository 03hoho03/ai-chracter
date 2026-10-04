import { describe, expect, it } from "vitest";

import { expandAuthorMacros } from "./authorMacros";
import { findAuthorMacroTypos, hasCharMacro } from "./authorMacroWarnings";

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

  // 오타로 알리는 모양은 대부분 이름으로 바뀌지 않고 글자 그대로 남는다.
  it("flags shapes the expander leaves as written", () => {
    for (const typo of ["{user}", "{{user}", "{user}}", "{{user", "<USER>"]) {
      expect(expandAuthorMacros(typo, NAMES)).toBe(typo);
    }
  });

  // 중괄호가 두 겹보다 많으면 엔진은 안쪽 `{{user}}` 를 이름으로 바꾸지만 남는 중괄호가 화면에 보인다. 그래서 이 모양도
  // 오타로 알린다 — "두 겹으로 쓰라"는 안내가 결과적으로 맞는 조언이다.
  it("flags extra braces even though the inner macro is replaced", () => {
    expect(expandAuthorMacros("{{{user}}}", NAMES)).toBe("{지훈}");
    expect(expandAuthorMacros("{{user}}}", NAMES)).toBe("지훈}");
    expect(findAuthorMacroTypos("{{{user}}}")).toEqual(["{{{user}}}"]);
    expect(findAuthorMacroTypos("{{user}}}")).toEqual(["{{user}}}"]);
  });
});

describe("hasCharMacro", () => {
  it("finds macros the expander replaces", () => {
    expect(hasCharMacro("{{ Char }}가 손을 흔든다")).toBe(true);
  });

  it("ignores typos and the other macro", () => {
    expect(hasCharMacro("{char} 와 {{user}}")).toBe(false);
  });
});
