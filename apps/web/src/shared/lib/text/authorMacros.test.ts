// 치환 표는 서버 테스트 `apps/api/tests/test_author_macros.py` 와 함께 읽는 JSON 하나다(`apps/web/test/authorMacroCases.ts`
// 가 편다) — 프롬프트는 서버 구현으로, 화면은 이 구현으로 바뀌므로 둘이 갈라지면 모델이 부른 이름과 화면의 이름이 다르다.
import { describe, expect, it } from "vitest";

import { loadAuthorMacroCases } from "../../../../test/authorMacroCases";

import {
  defaultUserNameError,
  expandAuthorMacros,
  FALLBACK_USER_NAME,
  resolveAuthorMacroNames,
  userNameError,
} from "./authorMacros";

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

describe("resolveAuthorMacroNames", () => {
  const base = {
    personaName: null,
    defaultUserName: "",
    contentType: "story",
    contentName: "상영회까지",
  } as const;

  it("uses the conversation profile name first", () => {
    expect(
      resolveAuthorMacroNames({
        ...base,
        personaName: "지훈",
        defaultUserName: "조감독",
      }).userName,
    ).toBe("지훈");
  });

  it("falls back to the work's default name when there is no profile", () => {
    expect(
      resolveAuthorMacroNames({ ...base, defaultUserName: "조감독" }).userName,
    ).toBe("조감독");
  });

  it("falls back to the fallback name when neither is set", () => {
    expect(resolveAuthorMacroNames(base).userName).toBe(FALLBACK_USER_NAME);
    expect(
      resolveAuthorMacroNames({
        ...base,
        personaName: undefined,
        defaultUserName: undefined,
      }).userName,
    ).toBe(FALLBACK_USER_NAME);
  });

  it("names {{char}} only for a character work", () => {
    expect(resolveAuthorMacroNames(base).charName).toBeNull();
    expect(
      resolveAuthorMacroNames({
        ...base,
        contentType: "character",
        contentName: "유나",
      }).charName,
    ).toBe("유나");
  });

  it("leaves {{char}} as written when a character work's name is unknown", () => {
    expect(
      resolveAuthorMacroNames({
        ...base,
        contentType: "character",
        contentName: undefined,
      }).charName,
    ).toBeNull();
  });
});

// 서버 `apps/api/tests/test_author_macros.py` 의 이름 규칙 표와 같은 입력이다 — 폼과 서버가 같은 이름을 막아야
// 폼을 통과한 이름이 서버 422 로 끝나지 않는다.
const REJECTED_NAMES = [
  ["colon", "지:훈"],
  ["newline", "지\n훈"],
  ["carriage-return", "지\r훈"],
  ["star", "*지훈*"],
  ["backtick", "`지훈`"],
  ["backslash", "지훈\\"],
  ["decimal-character-reference", "&#42;지훈"],
  ["hex-character-reference", "&#x2a;지훈"],
  ["named-character-reference", "&ast;지훈"],
  ["quote-marker", "> 지훈"],
  ["lone-quote-marker", ">"],
  ["dash-list-marker", "- 지훈"],
  ["lone-plus-list-marker", "+"],
  ["ordered-list-marker", "1. 지훈"],
  ["lone-paren-list-marker", "3)"],
  ["tilde-fence", "~~~지훈"],
  ["dash-rule", "---"],
  ["underscore-rule", "_ _ _"],
] as const;

const ACCEPTED_NAMES = [
  ["hangul", "지훈"],
  ["underscore", "민_수_"],
  ["emoticon-starting-with-angle", ">_<"],
  ["inner-dash", "김-민"],
  ["tilde", "별~"],
  ["double-tilde", "~~민~~"],
  ["ampersand", "R&B"],
  ["decimal-number", "1.5"],
  ["hash", "#민"],
  ["bracket", "[민]"],
  ["angle", "<민>"],
  ["two-dashes", "--"],
  ["braces", "{지훈}"],
] as const;

describe("userNameError", () => {
  it.each(REJECTED_NAMES)("rejects %s", (_id, name) => {
    expect(userNameError(name)).not.toBeNull();
    expect(defaultUserNameError(name)).not.toBeNull();
  });

  it.each(ACCEPTED_NAMES)("accepts %s", (_id, name) => {
    expect(userNameError(name)).toBeNull();
  });
});

describe("defaultUserNameError", () => {
  // 작품 기본 이름은 작가가 글과 함께 쓰는 칸이라 매크로나 이미지 태그를 이름 속에 숨겨 넣지 못하게 한다.
  it.each(["{지훈}", "{{char}}", "지}"])("also rejects braces (%s)", (name) => {
    expect(defaultUserNameError(name)).not.toBeNull();
  });

  it("accepts an empty name, which means the fallback name", () => {
    expect(defaultUserNameError("")).toBeNull();
  });
});
