import { describe, expect, it } from "vitest";

import { PAGE_TEXT_HEIGHT_PX, PAGE_TEXT_WIDTH_PX } from "./pageFormat";
import { toPageIllustrationBox } from "./pageIllustration";

// 판형 안 그림 상자는 응답의 너비·높이와 상수만으로 정해지는 px 크기다 — 창 크기·브라우저 기본 글자 크기와 무관해야
// 같은 화·같은 설정의 쪽 수가 기기마다 같다. 높이 상한은 스크롤 모드 글 속 그림과 같은 320px 이고 폭은 글 상자 폭에 걸린다.
describe("toPageIllustrationBox", () => {
  it.each([
    ["portrait 3:4", 768, 1024, { width: 240, height: 320 }],
    ["square", 1024, 1024, { width: 312, height: 312 }],
    ["landscape 16:9", 1280, 720, { width: 312, height: 176 }],
    ["very tall 1:4", 256, 1024, { width: 80, height: 320 }],
    ["very wide 4:1", 2048, 512, { width: 312, height: 78 }],
  ])("sizes a %s image inside the text box keeping its ratio", (_name, width, height, expected) => {
    expect(toPageIllustrationBox(width, height)).toEqual(expected);
  });

  it.each([
    [null, 1024],
    [768, null],
    [0, 1024],
    [768, 0],
    [null, null],
  ])("gives an unknown size (%s × %s) a fixed 3:4 slot", (width, height) => {
    expect(toPageIllustrationBox(width, height)).toEqual({ width: 240, height: 320 });
  });

  it("never exceeds the height cap or the text box width, and keeps the ratio within a pixel", () => {
    for (let width = 100; width <= 3000; width += 37) {
      for (const height of [97, 512, 719, 1024, 1999]) {
        const box = toPageIllustrationBox(width, height);
        expect(box.width).toBeLessThanOrEqual(PAGE_TEXT_WIDTH_PX);
        expect(box.height).toBeLessThanOrEqual(320);
        expect(box.height).toBeLessThan(PAGE_TEXT_HEIGHT_PX);
        expect(Number.isInteger(box.width) && Number.isInteger(box.height)).toBe(true);
        expect(Math.abs(box.height - (box.width * height) / width)).toBeLessThanOrEqual(1);
      }
    }
  });
});
