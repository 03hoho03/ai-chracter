import { describe, expect, it } from "vitest";

import { toResumeTarget } from "./resumeTarget";

function chapter(ordinal: number, finishedReading = false) {
  return { id: `c${ordinal}`, ordinal, finishedReading };
}

describe("toResumeTarget", () => {
  it("화가 없으면 갈 곳이 없다", () => {
    expect(toResumeTarget([], undefined)).toBeUndefined();
    expect(toResumeTarget([], "c1")).toBeUndefined();
  });

  it("읽은 기록이 없으면 첫 화부터", () => {
    expect(toResumeTarget([chapter(2), chapter(1)], undefined)).toEqual({ kind: "start", chapter: chapter(1) });
  });

  it("읽던 화를 다 읽지 않았으면 그 화", () => {
    expect(toResumeTarget([chapter(1, true), chapter(2), chapter(3)], "c2")).toEqual({
      kind: "continue",
      chapter: chapter(2),
    });
  });

  it("읽던 화를 다 읽었으면 그다음 화", () => {
    expect(toResumeTarget([chapter(1, true), chapter(2, true), chapter(3)], "c2")).toEqual({
      kind: "continue",
      chapter: chapter(3),
    });
  });

  it("다음 화는 목록 순서가 아니라 화 번호로 찾는다", () => {
    expect(toResumeTarget([chapter(3), chapter(1, true), chapter(2)], "c1")?.chapter).toEqual(chapter(2));
  });

  it("마지막 화까지 다 읽었으면 마지막 화", () => {
    expect(toResumeTarget([chapter(1, true), chapter(2, true)], "c2")).toEqual({
      kind: "continue",
      chapter: chapter(2, true),
    });
  });

  it("다음 화가 다른 이유로 다 읽은 화여도 그다음 화 하나로 간다", () => {
    expect(toResumeTarget([chapter(1, true), chapter(2, true), chapter(3)], "c1")?.chapter).toEqual(chapter(2, true));
  });

  it("읽던 화가 지워졌으면 아직 다 읽지 않은 첫 화, 그것도 없으면 마지막 화", () => {
    expect(toResumeTarget([chapter(1, true), chapter(2), chapter(3)], "gone")).toEqual({
      kind: "continue",
      chapter: chapter(2),
    });
    expect(toResumeTarget([chapter(1, true), chapter(2, true)], "gone")?.chapter).toEqual(chapter(2, true));
  });
});
