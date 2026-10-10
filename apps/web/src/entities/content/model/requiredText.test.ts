import { describe, expect, it } from "vitest";
import { z } from "zod";

import { isBlankText, requiredText } from "./requiredText";

describe("isBlankText", () => {
  it.each([
    ["빈 문자열", ""],
    ["반각 공백", "   "],
    ["줄바꿈·탭", "\n\t\r\n"],
    ["전각 공백", "　　"],
    ["줄바꿈 없는 공백(NBSP)", " "],
    ["BOM", "﻿"],
  ])("%s만이면 빈 칸이다", (_name, value) => {
    expect(isBlankText(value)).toBe(true);
  });

  it.each([
    ["글자", "유나"],
    ["앞뒤 공백 안의 글자", "  유나  "],
    // 화면 `trim()` 은 U+0085 를 지우지 않는다 — 서버도 같은 집합이라 이 값은 양쪽 모두 빈 칸이 아니다.
    ["U+0085", "\u0085"],
  ])("%s가 있으면 빈 칸이 아니다", (_name, value) => {
    expect(isBlankText(value)).toBe(false);
  });
});

describe("requiredText", () => {
  const schema = z.string().refine(...requiredText("이름을 입력해주세요"));

  it("공백만인 값은 주어진 문구로 거절한다", () => {
    const result = schema.safeParse("  \n");
    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.message).toBe("이름을 입력해주세요");
  });

  it("통과한 값은 앞뒤 공백을 자르지 않고 그대로 돌려준다", () => {
    expect(schema.parse("  유나 ")).toBe("  유나 ");
  });
});
