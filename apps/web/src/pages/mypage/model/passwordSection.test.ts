import { describe, expect, it } from "vitest";

import { getPasswordSection } from "./passwordSection";

describe("getPasswordSection", () => {
  it("비밀번호가 있으면 변경 폼이다", () => {
    expect(getPasswordSection({ hasPassword: true, socialProvider: null })).toEqual({
      kind: "change-password",
      heading: "비밀번호 변경",
    });
  });

  it("이메일 가입에 구글이 이어진 계정도 비밀번호가 있으니 폼을 유지한다", () => {
    expect(getPasswordSection({ hasPassword: true, socialProvider: "google" }).kind).toBe("change-password");
  });

  it.each([
    ["kakao", "카카오 계정으로 로그인하고 있어요."],
    ["google", "구글 계정으로 로그인하고 있어요."],
  ] as const)("비밀번호 없는 %s 계정은 폼 대신 로그인 방법을 알린다", (provider, expected) => {
    const section = getPasswordSection({ hasPassword: false, socialProvider: provider });

    expect(section.kind).toBe("social-login");
    expect(section.heading).toBe("로그인 방법");
    expect(section.kind === "social-login" && section.message).toContain(expected);
  });

  it("제공자를 모르면 이름 없이 소셜 계정이라고 한다", () => {
    const section = getPasswordSection({ hasPassword: false, socialProvider: null });

    expect(section.kind === "social-login" && section.message).toContain("소셜 계정으로 로그인하고 있어요.");
  });
});
