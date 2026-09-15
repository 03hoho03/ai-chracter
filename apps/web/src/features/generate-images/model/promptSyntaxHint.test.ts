import { describe, expect, it } from "vitest";

import {
  getPromptSyntaxHint,
  PROMPT_ATTACHED_PAREN_WEIGHT_WARNING,
  PROMPT_FULLWIDTH_PARENS_WARNING,
  PROMPT_UNBALANCED_PARENS_WARNING,
  PROMPT_WEIGHT_SYNTAX_HINT,
} from "./promptSyntaxHint";

describe("getPromptSyntaxHint", () => {
  it("괄호가 없으면 평소 문법 안내를 반환한다", () => {
    expect(getPromptSyntaxHint("1girl, solo, school uniform")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
  });

  describe("① ASCII 괄호 짝 불일치 — 경고 (현행 유지)", () => {
    it("여는 괄호만 있으면 경고한다", () => {
      expect(getPromptSyntaxHint("(긴 머리, school uniform")).toBe(PROMPT_UNBALANCED_PARENS_WARNING);
    });

    it("닫는 괄호가 여는 괄호보다 먼저 오면 경고한다", () => {
      expect(getPromptSyntaxHint(")a(")).toBe(PROMPT_UNBALANCED_PARENS_WARNING);
    });
  });

  describe("② 전각 괄호 포함 — 경고 (신규, 문자 검출만으로 판정)", () => {
    it("전각 괄호는 짝이 맞아도 경고한다 — 짝이 맞아도 무조건 리터럴이라 가중치가 안 먹는다", () => {
      expect(getPromptSyntaxHint("（긴 머리）1.3, school uniform")).toBe(PROMPT_FULLWIDTH_PARENS_WARNING);
    });

    it("전각 괄호는 짝이 안 맞아도 문자 검출만으로 경고한다 — 파싱·짝 맞추기가 불필요하다", () => {
      expect(getPromptSyntaxHint("（긴 머리, school uniform")).toBe(PROMPT_FULLWIDTH_PARENS_WARNING);
    });
  });

  describe("③ 문자(...)숫자 — 경고 (신규, 가중치 숫자가 붙은 경우로 한정)", () => {
    it("한글이 여는 괄호에 바로 붙고 가중치 숫자가 있으면 경고한다", () => {
      expect(getPromptSyntaxHint("소녀(단발)1.4, 교복")).toBe(PROMPT_ATTACHED_PAREN_WEIGHT_WARNING);
    });

    it("영문이 여는 괄호에 바로 붙고 가중치 숫자가 있으면 경고한다 — 언어 무관 동일 규칙", () => {
      expect(getPromptSyntaxHint("abc(tag)1.4")).toBe(PROMPT_ATTACHED_PAREN_WEIGHT_WARNING);
    });
  });

  describe("경고하지 않는 것 — 집 PC 실측으로 확정된 정상 패턴", () => {
    it("여는 괄호가 문장 시작이면(한글 내용) 짝이 맞는 한 경고하지 않는다", () => {
      expect(getPromptSyntaxHint("(긴 머리)1.3, school uniform")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });

    it("숫자 없는 대칭 괄호는 경고하지 않는다", () => {
      expect(getPromptSyntaxHint("(tag)")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });

    it("숫자 없는 중첩 괄호는 경고하지 않는다", () => {
      expect(getPromptSyntaxHint("((tag))")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });

    it("숫자 없는 3중 중첩 괄호는 경고하지 않는다", () => {
      expect(getPromptSyntaxHint("(((tag)))")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });

    it("중첩 괄호 + 가중치는 (tag)1.4와 동일하게 동작해 경고하지 않는다 — 중첩은 곱해지지 않는다", () => {
      expect(getPromptSyntaxHint("((tag))1.4")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });

    it("괄호 앞에 공백이 있으면(한글) 문법으로 파싱되어 경고하지 않는다 — diff 0.000000", () => {
      expect(getPromptSyntaxHint("소녀 (단발), 교복")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });

    it("괄호 앞에 공백이 있으면(영문) 문법으로 파싱되어 경고하지 않는다 — diff 0.000000", () => {
      expect(getPromptSyntaxHint("1girl (short hair), school uniform")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });

    it("괄호가 앞 글자에 붙어도 숫자가 없으면 경고하지 않는다 — 리터럴이 되어도 설명 의도가 남는다", () => {
      expect(getPromptSyntaxHint("소녀(단발), 교복")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });

    it("괄호 앞이 쉼표 직후면 정상 파싱되어 경고하지 않는다", () => {
      expect(getPromptSyntaxHint("소녀,(단발), 교복")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });

    it("(tag)1 은 경고하지 않는다", () => {
      expect(getPromptSyntaxHint("(tag)1")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });

    it("(tag)0.5 는 경고하지 않는다", () => {
      expect(getPromptSyntaxHint("(tag)0.5")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });

    it("(tag)2.0 은 경고하지 않는다", () => {
      expect(getPromptSyntaxHint("(tag)2.0")).toBe(PROMPT_WEIGHT_SYNTAX_HINT);
    });
  });

  describe("우선순위 — ② > ③ > ①", () => {
    it("전각 괄호와 ASCII 짝 불일치가 함께 있으면 전각 경고가 우선한다", () => {
      expect(getPromptSyntaxHint("（긴 머리)1.3, (school uniform")).toBe(PROMPT_FULLWIDTH_PARENS_WARNING);
    });

    it("문자(...)숫자 패턴과 ASCII 짝 불일치가 함께 있으면 ③ 경고가 우선한다", () => {
      expect(getPromptSyntaxHint("소녀(단발)1.4, (school uniform")).toBe(
        PROMPT_ATTACHED_PAREN_WEIGHT_WARNING,
      );
    });
  });
});
