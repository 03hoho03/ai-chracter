import { describe, expect, it } from "vitest";

import { toEscapeTarget } from "./escapeTarget";

describe("toEscapeTarget", () => {
  it("목차 시트가 열려 있으면 바·설정을 건드리지 않는다", () => {
    expect(toEscapeTarget({ isTocOpen: true, isSettingsOpen: false, isChromeVisible: true })).toBe("none");
    expect(toEscapeTarget({ isTocOpen: true, isSettingsOpen: true, isChromeVisible: true })).toBe("none");
  });

  it("보기 설정이 열려 있으면 설정만 닫는다", () => {
    expect(toEscapeTarget({ isTocOpen: false, isSettingsOpen: true, isChromeVisible: true })).toBe("settings");
  });

  it("바만 보이면 바를 숨긴다", () => {
    expect(toEscapeTarget({ isTocOpen: false, isSettingsOpen: false, isChromeVisible: true })).toBe("chrome");
  });

  it("아무것도 열려 있지 않으면 아무 일도 없다", () => {
    expect(toEscapeTarget({ isTocOpen: false, isSettingsOpen: false, isChromeVisible: false })).toBe("none");
  });
});
