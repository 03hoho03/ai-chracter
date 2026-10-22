import { describe, expect, it } from "vitest";

import { isFinishedScreen, toAnchorParagraphIndex, toCoveredAnchorTarget, toLeadScreens, toRestoreScreen } from "./pageAnchor";

// 문단 9개, 화면 7개(0~6). 5번 문단은 화면 2 에서 시작해 화면 3 을 통째로 덮고, 화면 6 은 화 끝 화면이다.
const START_SCREENS = [0, 0, 0, 1, 1, 2, 4, 5, 5];
const END_SCREEN = 6;

const anchorOf = (screen: number) => toAnchorParagraphIndex({ leadScreens: START_SCREENS, screen });

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
    expect(toAnchorParagraphIndex({ leadScreens: [0], screen: 0 })).toBe(0);
    expect(toAnchorParagraphIndex({ leadScreens: [0], screen: 1 })).toBe(0);
  });
});

describe("toRestoreScreen", () => {
  const restore = (anchor: Parameters<typeof toRestoreScreen>[0]["anchor"], offsetScreen?: number) =>
    toRestoreScreen({ anchor, leadScreens: START_SCREENS, endScreen: END_SCREEN, offsetScreen });

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

// 그림이 든 화. 문단의 머리는 그 문단 앞 그림들(문단 0 이면 화 머리)이고, 쪽을 대표하는 문단·되돌릴 화면을 머리가
// 시작하는 화면으로 잰다. 그림 없는 화에서는 머리 = 문단 자신이라 위 시험의 값 그대로다.
describe("toLeadScreens", () => {
  it("equals the paragraph start screens when the chapter has no illustrations", () => {
    expect(toLeadScreens({ startScreens: START_SCREENS, illustrations: [] })).toEqual(START_SCREENS);
  });

  it("keeps the first paragraph on the first screen even when an illustration ahead of it pushed its text to the next", () => {
    // 첫 쪽에 화 머리만 남고, 문단 0 앞 그림과 문단 0 글은 둘째 화면에서 시작한다.
    expect(
      toLeadScreens({ startScreens: [1, 1, 2], illustrations: [{ paragraphIndex: 0, placement: "before", screen: 1 }] }),
    ).toEqual([0, 1, 2]);
  });

  it("starts a paragraph where its first before-illustration starts", () => {
    expect(
      toLeadScreens({
        startScreens: [0, 0, 3, 3],
        illustrations: [
          { paragraphIndex: 0, placement: "after", screen: 1 },
          { paragraphIndex: 2, placement: "before", screen: 2 },
          { paragraphIndex: 2, placement: "before", screen: 3 },
        ],
      }),
    ).toEqual([0, 0, 2, 3]);
  });
});

describe("anchoring with illustrations", () => {
  // 문단 0 은 화면 0, 문단 1 앞 세로 그림 둘이 화면 1·2 를 하나씩, 문단 1 글은 화면 3, 문단 2 는 화면 4, 화 끝 5.
  const LEADS = toLeadScreens({
    startScreens: [0, 3, 4],
    illustrations: [
      { paragraphIndex: 1, placement: "before", screen: 1 },
      { paragraphIndex: 1, placement: "before", screen: 2 },
    ],
  });

  it("opens a chapter whose first screen holds only the header on that first screen", () => {
    const leads = toLeadScreens({ startScreens: [1, 2], illustrations: [{ paragraphIndex: 0, placement: "before", screen: 1 }] });
    expect(toRestoreScreen({ anchor: { paragraphIndex: 0, charOffset: 0, isAtEnd: false }, leadScreens: leads, endScreen: 3 })).toBe(0);
    expect(toAnchorParagraphIndex({ leadScreens: leads, screen: 0 })).toBe(0);
  });

  it("gives a screen holding only a paragraph's before-illustration to that paragraph, and restores to it", () => {
    expect(toAnchorParagraphIndex({ leadScreens: LEADS, screen: 1 })).toBe(1);
    expect(toRestoreScreen({ anchor: { paragraphIndex: 1, charOffset: 0, isAtEnd: false }, leadScreens: LEADS, endScreen: 5 })).toBe(1);
  });

  it("restores a screen held by an illustration to the screen that illustration is on", () => {
    expect(
      toRestoreScreen({
        anchor: { paragraphIndex: 1, charOffset: 0, isAtEnd: false, illustrationKey: "1-before-1" },
        leadScreens: LEADS,
        endScreen: 5,
        illustrationScreen: 2,
      }),
    ).toBe(2);
  });
});

describe("toCoveredAnchorTarget", () => {
  it("picks the text when the covering paragraph's text is on the screen", () => {
    expect(toCoveredAnchorTarget({ screen: 3, textStartScreen: 2, textEndScreen: 4, illustrations: [] })).toEqual({ kind: "text" });
    expect(
      toCoveredAnchorTarget({
        screen: 3,
        textStartScreen: 2,
        textEndScreen: 3,
        illustrations: [{ key: "k-after-0", placement: "after", screen: 3 }],
      }),
    ).toEqual({ kind: "text" });
  });

  it("picks the after-illustration that holds a screen alone past the end of the text", () => {
    expect(
      toCoveredAnchorTarget({
        screen: 4,
        textStartScreen: 2,
        textEndScreen: 3,
        illustrations: [
          { key: "k-after-0", placement: "after", screen: 3 },
          { key: "k-after-1", placement: "after", screen: 4 },
        ],
      }),
    ).toEqual({ kind: "illustration", key: "k-after-1" });
  });

  it("picks the before-illustration that opens a screen ahead of the text", () => {
    expect(
      toCoveredAnchorTarget({
        screen: 2,
        textStartScreen: 2,
        textEndScreen: 2,
        illustrations: [
          { key: "k-before-0", placement: "before", screen: 1 },
          { key: "k-before-1", placement: "before", screen: 2 },
        ],
      }),
    ).toEqual({ kind: "illustration", key: "k-before-1" });
  });
});
