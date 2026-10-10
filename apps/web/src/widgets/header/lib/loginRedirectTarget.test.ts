import { describe, expect, it } from "vitest";

import { loginRedirectTarget } from "./loginRedirectTarget";

describe("loginRedirectTarget", () => {
  it("returns the current href outside the auth flow", () => {
    expect(loginRedirectTarget({ pathname: "/chats", href: "/chats?tab=1", search: { tab: 1 } })).toBe("/chats?tab=1");
  });

  it.each(["/login", "/signup", "/onboarding/kakao"])("carries the existing redirect on %s", (pathname) => {
    expect(loginRedirectTarget({ pathname, href: `${pathname}?redirect=%2Fchats`, search: { redirect: "/chats" } })).toBe(
      "/chats",
    );
  });

  it("drops the redirect on an auth flow screen that has none", () => {
    expect(loginRedirectTarget({ pathname: "/login", href: "/login", search: {} })).toBeUndefined();
  });
});
