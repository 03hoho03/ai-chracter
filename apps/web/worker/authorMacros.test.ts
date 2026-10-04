// 앱 구현·서버 구현과 같은 입력 표로 이 사본을 시험한다 — 링크 미리보기의 이름이 화면·모델과 갈라지지 않게.
import { describe, expect, it } from "vitest";

import authorMacroCases from "../../api/tests/fixtures/author_macro_cases.json";
import { expandAuthorMacros, FALLBACK_USER_NAME } from "./authorMacros";

describe("expandAuthorMacros (Worker copy)", () => {
  it.each(
    authorMacroCases.expand.map((row) => [
      row.id,
      row.text,
      row.userName,
      row.charName,
      row.expected,
    ]),
  )("%s", (_id, text, userName, charName, expected) => {
    expect(expandAuthorMacros(text, { userName, charName })).toBe(expected);
  });

  it("uses the same fallback name as the table", () => {
    expect(
      authorMacroCases.expand.find((row) => row.id === "fallback-name")
        ?.userName,
    ).toBe(FALLBACK_USER_NAME);
  });
});
