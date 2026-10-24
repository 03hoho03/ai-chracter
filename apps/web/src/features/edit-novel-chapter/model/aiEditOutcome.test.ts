import { describe, expect, it } from "vitest";

import { toAiEditOutcome, toBlockEditArrivedMessage } from "./aiEditOutcome";

const preview = { baseRevisionId: "r1", paragraphStart: 0, paragraphEnd: 1, instruction: "짧게", resultText: "본문" };
const emptied = { ...preview, instruction: null, resultText: null };

describe("toAiEditOutcome", () => {
  it("수정안 본문이 있으면 미리보기다", () => {
    expect(toAiEditOutcome({ revisionId: null, chapterId: "c1", aiEdit: preview })).toEqual({ kind: "preview" });
  });

  it("본문이 비었고 적용 개정이 있으면 이미 적용했다", () => {
    expect(toAiEditOutcome({ revisionId: "r2", chapterId: "c1", aiEdit: emptied })).toEqual({
      kind: "unavailable",
      message: "이 수정안은 다른 곳에서 이미 적용했어요.",
    });
  });

  it("본문이 비었고 화가 없으면 화가 지워졌다", () => {
    expect(toAiEditOutcome({ revisionId: null, chapterId: null, aiEdit: emptied })).toEqual({
      kind: "unavailable",
      message: "화가 지워져 수정안을 쓸 수 없어요.",
    });
  });

  it("그 밖의 빈 본문은 화가 바뀐 것이다", () => {
    expect(toAiEditOutcome({ revisionId: null, chapterId: "c1", aiEdit: emptied })).toEqual({
      kind: "unavailable",
      message: "그사이 화가 바뀌어 이 수정안은 적용할 수 없어요.",
    });
  });

  it("미리보기 칸 자체가 없어도 미리보기로 보지 않는다", () => {
    expect(toAiEditOutcome({ revisionId: null, chapterId: "c1", aiEdit: null }).kind).toBe("unavailable");
  });
});

describe("toAiEditOutcome — 여러 문단 수정", () => {
  // 여러 문단 수정 작업은 장 전체 결과 본문을 늘 비운다. 본문이 없다고 "화가 바뀌었다"고 알리면 성공한 작업을 실패로 말한다.
  const blockEdit = { baseRevisionId: "r1", paragraphStart: null, paragraphEnd: null, instruction: "짧게", resultText: null };

  it("문단 범위가 빈 성공 작업은 블록별 수정안이다", () => {
    expect(toAiEditOutcome({ revisionId: null, chapterId: "c1", aiEdit: blockEdit })).toEqual({ kind: "patches" });
  });

  it("일부를 다른 곳에서 적용했어도(결과 개정이 차 있어도) 블록별 수정안이다", () => {
    expect(toAiEditOutcome({ revisionId: "r2", chapterId: "c1", aiEdit: blockEdit })).toEqual({ kind: "patches" });
  });
});

describe("toBlockEditArrivedMessage", () => {
  it("쓸 수 있는 수정안 수를 말한다", () => {
    expect(toBlockEditArrivedMessage(3, 2)).toBe("3화 수정안 2개가 왔어요. 고른 문단 자리에서 적용하거나 버릴 수 있어요.");
  });

  it("쓸 수 있는 수정안이 없으면 그렇다고 말한다", () => {
    expect(toBlockEditArrivedMessage(3, 0)).toBe("3화 수정안이 왔지만 지금 적용할 수 있는 수정안이 없어요.");
  });

  it("상세를 받지 못해 수를 모르면 수를 말하지 않는다", () => {
    expect(toBlockEditArrivedMessage(3, undefined)).toBe("3화 수정안이 왔어요. 고른 문단 자리에서 적용하거나 버릴 수 있어요.");
  });

  it("화를 모르면 화 번호를 빼고 말한다", () => {
    expect(toBlockEditArrivedMessage(undefined, 1)).toBe("수정안 1개가 왔어요. 고른 문단 자리에서 적용하거나 버릴 수 있어요.");
  });
});
