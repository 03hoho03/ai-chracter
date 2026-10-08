import { describe, expect, it } from "vitest";

import { type PageKeyFocus, toPageKeyAction } from "./pageKey";

const press = (key: string, options: { shiftKey?: boolean; hasModifier?: boolean; focus?: PageKeyFocus } = {}) =>
  toPageKeyAction({ key, shiftKey: false, hasModifier: false, focus: "none", ...options });

describe("toPageKeyAction", () => {
  it("화살표·PageUp/PageDown·Space 로 넘기고 Home/End 로 처음·화 끝으로 간다", () => {
    expect(press("ArrowLeft")).toBe("previous");
    expect(press("ArrowRight")).toBe("next");
    expect(press("PageUp")).toBe("previous");
    expect(press("PageDown")).toBe("next");
    expect(press(" ")).toBe("next");
    expect(press(" ", { shiftKey: true })).toBe("previous");
    expect(press("Home")).toBe("first");
    expect(press("End")).toBe("last");
  });

  it("다른 키는 넘기지 않는다", () => {
    expect(press("ArrowDown")).toBeUndefined();
    expect(press("Enter")).toBeUndefined();
    expect(press("Escape")).toBeUndefined();
  });

  it("Ctrl·Meta·Alt 가 함께 눌렸으면 넘기지 않는다", () => {
    expect(press("ArrowRight", { hasModifier: true })).toBeUndefined();
    expect(press(" ", { hasModifier: true })).toBeUndefined();
    expect(press("Home", { hasModifier: true })).toBeUndefined();
  });

  it("입력칸·슬라이더·설정 패널·목차 시트에 포커스가 있으면 어떤 키도 넘기지 않는다", () => {
    for (const focus of ["text", "slider", "panel"] as const) {
      expect(press("ArrowRight", { focus })).toBeUndefined();
      expect(press("PageDown", { focus })).toBeUndefined();
      expect(press(" ", { focus })).toBeUndefined();
      expect(press("End", { focus })).toBeUndefined();
    }
  });

  it("버튼·링크에 포커스가 있으면 Space 만 그 요소에 맡기고 나머지 키는 넘긴다", () => {
    expect(press(" ", { focus: "control" })).toBeUndefined();
    expect(press(" ", { focus: "control", shiftKey: true })).toBeUndefined();
    expect(press("ArrowRight", { focus: "control" })).toBe("next");
    expect(press("Home", { focus: "control" })).toBe("first");
  });
});
