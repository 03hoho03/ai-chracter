import { describe, expect, it } from "vitest";

import { toAiEditOutcome } from "./aiEditOutcome";

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

  it("본문이 비었고 장이 없으면 장이 지워졌다", () => {
    expect(toAiEditOutcome({ revisionId: null, chapterId: null, aiEdit: emptied })).toEqual({
      kind: "unavailable",
      message: "장이 지워져 수정안을 쓸 수 없어요.",
    });
  });

  it("그 밖의 빈 본문은 장이 바뀐 것이다", () => {
    expect(toAiEditOutcome({ revisionId: null, chapterId: "c1", aiEdit: emptied })).toEqual({
      kind: "unavailable",
      message: "그사이 장이 바뀌어 이 수정안은 적용할 수 없어요.",
    });
  });

  it("미리보기 칸 자체가 없어도 미리보기로 보지 않는다", () => {
    expect(toAiEditOutcome({ revisionId: null, chapterId: "c1", aiEdit: null }).kind).toBe("unavailable");
  });
});
