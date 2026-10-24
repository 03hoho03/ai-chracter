import { describe, expect, it } from "vitest";

import { toChapterNotice } from "./chapterNotice";

describe("toChapterNotice", () => {
  it("새 동작을 시작하면 이전 결과·거절 문장을 지운다", () => {
    expect(toChapterNotice({ type: "started" })).toBeUndefined();
  });

  it("되돌리면 몇 화를 몇 판으로 되돌렸는지 말한다", () => {
    expect(toChapterNotice({ type: "restored", chapterOrdinal: 1, revisionNo: 2 })).toEqual({
      tone: "info",
      message: "1화를 2판으로 되돌렸어요. 되돌리기 전 글도 판 이력에 남아요.",
    });
  });

  it("수정안을 적용하면 그 화에 적용했다고 말한다", () => {
    expect(toChapterNotice({ type: "applied", chapterOrdinal: 3 })).toEqual({
      tone: "info",
      message: "3화에 수정안을 적용했어요. 이전 글은 판 이력에 남아요.",
    });
  });

  it("수정안을 버리면 몇 화의 수정안을 버렸는지 말한다", () => {
    expect(toChapterNotice({ type: "dismissed", chapterOrdinal: 2 })).toEqual({ tone: "info", message: "2화 수정안을 버렸어요." });
  });

  it("직접 고치기의 세 끝(저장·바뀐 것 없음·그만둠)을 각각 몇 화의 일인지와 함께 말한다", () => {
    expect(toChapterNotice({ type: "manualSaved", chapterOrdinal: 1 })).toEqual({
      tone: "info",
      message: "1화를 고쳐 저장했어요. 이전 글은 판 이력에 남아요.",
    });
    expect(toChapterNotice({ type: "manualUnchanged", chapterOrdinal: 1 })).toEqual({
      tone: "info",
      message: "1화는 바뀐 내용이 없어 그대로 두었어요.",
    });
    expect(toChapterNotice({ type: "manualCancelled", chapterOrdinal: 1 })).toEqual({
      tone: "info",
      message: "1화 직접 고치기를 그만뒀어요.",
    });
  });

  it("거절은 받은 문장을 오류로 남긴다", () => {
    expect(toChapterNotice({ type: "rejected", message: "다른 곳에서 먼저 고쳤어요. 최신 내용을 불러왔어요." })).toEqual({
      tone: "error",
      message: "다른 곳에서 먼저 고쳤어요. 최신 내용을 불러왔어요.",
    });
  });
});

describe("toChapterNotice — 여러 문단 수정안", () => {
  it("하나를 적용·버리면 옛 수정안과 같은 문장이다", () => {
    expect(toChapterNotice({ type: "patchesApplied", chapterOrdinal: 2, count: 1 })).toEqual(
      toChapterNotice({ type: "applied", chapterOrdinal: 2 }),
    );
    expect(toChapterNotice({ type: "patchesDismissed", chapterOrdinal: 2, count: 1 })).toEqual(
      toChapterNotice({ type: "dismissed", chapterOrdinal: 2 }),
    );
  });

  it("여럿이면 몇 개를 함께 적용·버렸는지 말한다", () => {
    expect(toChapterNotice({ type: "patchesApplied", chapterOrdinal: 2, count: 3 })).toEqual({
      tone: "info",
      message: "2화에 수정안 3개를 함께 적용했어요. 이전 글은 판 이력에 남아요.",
    });
    expect(toChapterNotice({ type: "patchesDismissed", chapterOrdinal: 2, count: 3 })).toEqual({
      tone: "info",
      message: "2화 수정안 3개를 버렸어요.",
    });
  });
});

// 다시 검사 결과는 서버가 저장하지 않는 판단 이유를 그대로 함께 보인다 — 모델이 쓴 문장임을 앞말로 가른다.
describe("toChapterNotice — 묶음 다시 검사", () => {
  it("따로 적용해도 되면 남은 수정안을 따로 적용할 수 있다고 말한다", () => {
    expect(toChapterNotice({ type: "bundleRechecked", chapterOrdinal: 2, separable: true, reason: "서로 기대지 않아요." })).toEqual({
      tone: "info",
      message: "2화 묶음을 다시 검사했어요. 남은 수정안은 따로 적용할 수 있어요. AI 판단: 서로 기대지 않아요.",
    });
  });

  it("따로 적용할 수 없으면 묶음이 그대로이고 함께 버릴 수 있다고 말한다", () => {
    expect(toChapterNotice({ type: "bundleRechecked", chapterOrdinal: 2, separable: false, reason: "대사를 받아요." })).toEqual({
      tone: "info",
      message:
        "2화 묶음을 다시 검사했어요. 남은 수정안도 고친 문단과 이어져 있어 따로 적용할 수 없어요. 함께 버릴 수 있어요. AI 판단: 대사를 받아요.",
    });
  });

  it("판단 이유가 비었으면 앞말 없이 끝낸다", () => {
    expect(toChapterNotice({ type: "bundleRechecked", chapterOrdinal: 2, separable: true, reason: "  " })?.message).toBe(
      "2화 묶음을 다시 검사했어요. 남은 수정안은 따로 적용할 수 있어요.",
    );
  });
});
