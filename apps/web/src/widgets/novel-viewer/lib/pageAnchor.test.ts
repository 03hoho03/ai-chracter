import { describe, expect, it } from "vitest";

import { isFinishedScreen, toAnchorParagraphIndex, toRestoreScreen } from "./pageAnchor";

// 문단 9개, 화면 7개(0~6). 5번 문단은 화면 2 에서 시작해 화면 3 을 통째로 덮고, 화면 6 은 화 끝 화면이다.
const START_SCREENS = [0, 0, 0, 1, 1, 2, 4, 5, 5];
const END_SCREEN = 6;

const anchorOf = (screen: number) => toAnchorParagraphIndex({ startScreens: START_SCREENS, screen });

describe("toAnchorParagraphIndex", () => {
  it("그 화면에서 시작하는 첫 문단을 고른다", () => {
    expect(anchorOf(0)).toBe(0);
    expect(anchorOf(1)).toBe(3);
    expect(anchorOf(2)).toBe(5);
    expect(anchorOf(4)).toBe(6);
    expect(anchorOf(5)).toBe(7);
  });

  it("시작하는 문단이 없는 화면은 덮고 있는 문단이다", () => {
    expect(anchorOf(3)).toBe(5);
  });

  it("문단이 시작하지 않는 화 끝 화면은 마지막 문단이다", () => {
    expect(anchorOf(6)).toBe(8);
  });

  it("문단 하나짜리 화는 어느 화면이든 그 문단이다", () => {
    expect(toAnchorParagraphIndex({ startScreens: [0], screen: 0 })).toBe(0);
    expect(toAnchorParagraphIndex({ startScreens: [0], screen: 1 })).toBe(0);
  });
});

describe("toRestoreScreen", () => {
  const restore = (anchor: Parameters<typeof toRestoreScreen>[0]["anchor"], offsetScreen?: number) =>
    toRestoreScreen({ anchor, startScreens: START_SCREENS, endScreen: END_SCREEN, offsetScreen });

  it("문단 번호만 있으면 그 문단이 시작하는 화면으로 간다", () => {
    expect(restore({ paragraphIndex: 4, charOffset: 0, isAtEnd: false })).toBe(1);
    expect(restore({ paragraphIndex: 5, charOffset: 0, isAtEnd: false })).toBe(2);
  });

  it("덮인 화면은 글자 위치로 잰 화면으로 돌아가 앞 화면으로 밀리지 않는다", () => {
    expect(restore({ paragraphIndex: 5, charOffset: 812, isAtEnd: false }, 3)).toBe(3);
  });

  it("화 끝 화면에 있었으면 마지막 문단 화면이 아니라 화 끝 화면으로 간다", () => {
    expect(restore({ paragraphIndex: 8, charOffset: 0, isAtEnd: true })).toBe(6);
    expect(restore({ paragraphIndex: 8, charOffset: 0, isAtEnd: false })).toBe(5);
  });

  it("고른 화면에서 고른 앵커로 되돌아가면 같은 화면이다", () => {
    for (let screen = 0; screen <= END_SCREEN; screen += 1) {
      if (screen === 3) continue; // 덮인 화면은 글자 위치가 있어야 왕복한다(위 케이스)
      const paragraphIndex = anchorOf(screen);
      expect(restore({ paragraphIndex, charOffset: 0, isAtEnd: screen === END_SCREEN })).toBe(screen);
    }
  });

  it("본문이 줄어 문단 번호가 넘치면 마지막 문단 화면으로 간다", () => {
    expect(restore({ paragraphIndex: 40, charOffset: 0, isAtEnd: false })).toBe(5);
  });

  it("잰 화면이 화 끝을 넘으면 화 끝 화면으로 자른다", () => {
    expect(restore({ paragraphIndex: 8, charOffset: 30, isAtEnd: false }, 9)).toBe(6);
  });
});

describe("isFinishedScreen", () => {
  it("마지막 문단이 시작하는 화면부터 다 읽음이다", () => {
    expect(isFinishedScreen({ screen: 4, lastParagraphScreen: 5 })).toBe(false);
    expect(isFinishedScreen({ screen: 5, lastParagraphScreen: 5 })).toBe(true);
  });

  it("화 끝 화면으로 바로 건너뛰어도 다 읽음이다", () => {
    expect(isFinishedScreen({ screen: 6, lastParagraphScreen: 5 })).toBe(true);
  });

  it("한 화면짜리 화는 열자마자 다 읽음이다", () => {
    expect(isFinishedScreen({ screen: 0, lastParagraphScreen: 0 })).toBe(true);
  });
});
