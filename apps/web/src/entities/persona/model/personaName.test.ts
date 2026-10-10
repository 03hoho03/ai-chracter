import { describe, expect, it } from "vitest";

import { PERSONA_NAME_MAX_LENGTH } from "./persona";
import { personaNameIssue } from "./personaName";

describe("personaNameIssue", () => {
  it("accepts a name surrounded by spaces", () => {
    expect(personaNameIssue("  지훈  ")).toBeNull();
  });

  it("measures the length after trimming", () => {
    expect(personaNameIssue(` ${"가".repeat(PERSONA_NAME_MAX_LENGTH)} `)).toBeNull();
    expect(personaNameIssue("가".repeat(PERSONA_NAME_MAX_LENGTH + 1))).not.toBeNull();
  });

  it.each(["", "   "])("rejects a blank name %j", (value) => {
    expect(personaNameIssue(value)).toBe("이름을 입력해주세요");
  });

  // 이름이 작가 글 속 `{{user}}` 자리에 들어가면 표기로 바뀌는 문자.
  it.each(["지:훈", "*지훈*", "> 지훈"])("rejects %j", (value) => {
    expect(personaNameIssue(value)).not.toBeNull();
  });
});
