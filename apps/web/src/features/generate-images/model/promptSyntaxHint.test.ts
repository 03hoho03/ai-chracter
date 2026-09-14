import { describe, expect, it } from "vitest";

import {
  getPromptSyntaxHint,
  PROMPT_UNBALANCED_PARENS_WARNING,
  PROMPT_WEIGHT_SYNTAX_HINT,
} from "./promptSyntaxHint";

describe("getPromptSyntaxHint", () => {
  it("괄호가 없으면 평소 문법 안내를 반환한다", () => {
    expect(getPromptSyntaxHint("1girl, solo, school uniform")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
  });

  it("괄호 짝이 맞으면 평소 문법 안내를 반환한다", () => {
    expect(getPromptSyntaxHint("(긴 머리)1.3, school uniform")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
  });

  it("괄호 짝이 안 맞으면 경고로 전환한다", () => {
    expect(getPromptSyntaxHint("(긴 머리, school uniform")).toBe(PROMPT_UNBALANCED_PARENS_WARNING);
  });

  it("닫는 괄호가 여는 괄호보다 먼저 오면 경고로 전환한다", () => {
    expect(getPromptSyntaxHint(")a(")).toBe(PROMPT_UNBALANCED_PARENS_WARNING);
  });
});
