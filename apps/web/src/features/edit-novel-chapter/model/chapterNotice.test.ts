import { describe, expect, it } from "vitest";

import { toChapterNotice } from "./chapterNotice";

describe("toChapterNotice", () => {
  it("새 동작을 시작하면 이전 결과·거절 문장을 지운다", () => {
    expect(toChapterNotice({ type: "started" })).toBeUndefined();
  });

  it("되돌리면 몇 장을 몇 판으로 되돌렸는지 말한다", () => {
    expect(toChapterNotice({ type: "restored", chapterOrdinal: 1, revisionNo: 2 })).toEqual({
      tone: "info",
      message: "1장을 2판으로 되돌렸어요. 되돌리기 전 글도 판 이력에 남아요.",
    });
  });

  it("수정안을 적용하면 그 장에 적용했다고 말한다", () => {
    expect(toChapterNotice({ type: "applied", chapterOrdinal: 3 })).toEqual({
      tone: "info",
      message: "3장에 수정안을 적용했어요. 이전 글은 판 이력에 남아요.",
    });
  });

  it("수정안을 버리면 버렸다고 말한다", () => {
    expect(toChapterNotice({ type: "dismissed" })).toEqual({ tone: "info", message: "수정안을 버렸어요." });
  });

  it("직접 고치기의 세 끝(저장·바뀐 것 없음·그만둠)을 각각 말한다", () => {
    expect(toChapterNotice({ type: "manualSaved" })).toEqual({
      tone: "info",
      message: "고친 내용을 저장했어요. 이전 글은 판 이력에 남아요.",
    });
    expect(toChapterNotice({ type: "manualUnchanged" })).toEqual({
      tone: "info",
      message: "바뀐 내용이 없어 그대로 두었어요.",
    });
    expect(toChapterNotice({ type: "manualCancelled" })).toEqual({
      tone: "info",
      message: "직접 고치기를 그만뒀어요.",
    });
  });

  it("거절은 받은 문장을 오류로 남긴다", () => {
    expect(toChapterNotice({ type: "rejected", message: "다른 곳에서 먼저 고쳤어요. 최신 내용을 불러왔어요." })).toEqual({
      tone: "error",
      message: "다른 곳에서 먼저 고쳤어요. 최신 내용을 불러왔어요.",
    });
  });
});
