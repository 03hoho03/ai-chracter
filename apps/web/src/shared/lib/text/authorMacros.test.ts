// 치환 표는 서버 테스트 `apps/api/tests/test_author_macros.py` 와 함께 읽는 JSON 하나다(`apps/web/test/authorMacroCases.ts`
// 가 편다) — 프롬프트는 서버 구현으로, 화면은 이 구현으로 바뀌므로 둘이 갈라지면 모델이 부른 이름과 화면의 이름이 다르다.
import { describe, expect, it } from "vitest";

import { loadAuthorMacroCases } from "../../../../test/authorMacroCases";

import { expandAuthorMacros, FALLBACK_USER_NAME } from "./authorMacros";

const CASES = loadAuthorMacroCases();

describe("expandAuthorMacros", () => {
  it.each(CASES)("%s", (_id, text, userName, charName, expected) => {
    expect(expandAuthorMacros(text, { userName, charName })).toBe(expected);
  });

  it("the fallback row tests the exported fallback name", () => {
    expect(CASES.find(([id]) => id === "fallback-name")?.[2]).toBe(
      FALLBACK_USER_NAME,
    );
  });
});
