import { describe, expect, it } from "vitest";

import {
  assembleChapterBody,
  countChapterChars,
  joinParagraphRange,
  splitChapterParagraphs,
  toAiEditComparison,
} from "./chapterBody";

describe("splitChapterParagraphs", () => {
  it("빈 줄로 나누고 공백만 있는 줄도 빈 줄로 본다", () => {
    expect(splitChapterParagraphs("가\n\n나\n \t\n다")).toEqual(["가", "나", "다"]);
  });

  it("문단 안 줄바꿈 하나는 두고 앞뒤 공백과 빈 문단은 버린다", () => {
    expect(splitChapterParagraphs("  가\n가2  \n\n\n\n 나 \n\n")).toEqual(["가\n가2", "나"]);
  });

  it("비었거나 공백뿐이면 문단이 없다", () => {
    expect(splitChapterParagraphs("  \n\n ")).toEqual([]);
  });
});

describe("assembleChapterBody", () => {
  const paragraphs = ["하나", "둘", "셋", "넷"];

  it("고른 범위만 입력한 글로 바꾸고 나머지는 그대로 잇는다", () => {
    expect(assembleChapterBody(paragraphs, { start: 1, end: 2 }, "새 둘\n\n새 셋\n\n새 넷")).toBe(
      "하나\n\n새 둘\n\n새 셋\n\n새 넷\n\n넷",
    );
  });

  it("입력칸을 비우면 고른 문단이 빠진다", () => {
    expect(assembleChapterBody(paragraphs, { start: 0, end: 0 }, "   ")).toBe("둘\n\n셋\n\n넷");
  });

  it("고치지 않은 글이면 원래 본문과 같다", () => {
    const range = { start: 1, end: 3 };
    expect(assembleChapterBody(paragraphs, range, joinParagraphRange(paragraphs, range))).toBe(paragraphs.join("\n\n"));
  });
});

describe("countChapterChars", () => {
  it("앞뒤 공백을 빼고 코드 포인트로 센다", () => {
    expect(countChapterChars("  가😀나 ")).toBe(3);
  });
});

describe("toAiEditComparison", () => {
  const paragraphs = ["하나", "둘", "셋", "넷", "다섯"];

  it("수정안에서 앞뒤 그대로인 문단을 덜어 고친 자리만 꺼낸다", () => {
    const result = "하나\n\n새 둘\n\n새 둘 반\n\n새 셋\n\n넷\n\n다섯";
    expect(toAiEditComparison(paragraphs, result, { start: 1, end: 2 })).toEqual({
      original: ["둘", "셋"],
      candidate: ["새 둘", "새 둘 반", "새 셋"],
    });
  });

  it("문단이 줄어든 수정안도 자리를 맞춘다", () => {
    const result = "하나\n\n둘셋넷 합침\n\n다섯";
    expect(toAiEditComparison(paragraphs, result, { start: 1, end: 3 })).toEqual({
      original: ["둘", "셋", "넷"],
      candidate: ["둘셋넷 합침"],
    });
  });

  it("마지막 문단까지 고른 범위", () => {
    expect(toAiEditComparison(paragraphs, "하나\n\n둘\n\n셋\n\n넷\n\n끝", { start: 4, end: 4 })).toEqual({
      original: ["다섯"],
      candidate: ["끝"],
    });
  });

  it("셈이 맞지 않으면 수정안 전체를 후보로 보인다", () => {
    expect(toAiEditComparison(paragraphs, "짧은 글", { start: 3, end: 3 }).candidate).toEqual(["짧은 글"]);
  });
});
