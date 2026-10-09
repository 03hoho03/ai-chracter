import { describe, expect, it } from "vitest";

import { caseFoldKey } from "./caseFoldKey";

describe("caseFoldKey", () => {
  it("folds letter case and Unicode composition the way the server compares keywords", () => {
    expect(caseFoldKey("USB")).toBe("usb");
    expect(caseFoldKey("한밤".normalize("NFD"))).toBe("한밤");
    // 파이썬 casefold 는 ß·ẞ 를 ss 로 접는다 — 소문자화만으로는 이 둘이 서버보다 느슨해진다.
    expect(caseFoldKey("ẞ")).toBe(caseFoldKey("ss"));
    expect(caseFoldKey("ß")).toBe(caseFoldKey("SS"));
  });
});
