import { describe, expect, it } from "vitest";

import {
  factHeading,
  forgetFactConfirmLabel,
  forgetSceneTitle,
  impressionSourceLabel,
  itemCountLabel,
  MEMORY_COMEBACK_NOTICE,
  turnRangeLabel,
  usedInRepliesText,
} from "./memoryItemText";

describe("factHeading", () => {
  it("writes a relation as subject → object", () => {
    expect(factHeading({ kind: "relation", subject: "점장", object: "서아", attribute: undefined })).toBe("점장 → 서아");
  });

  it("writes a fact as subject · attribute", () => {
    expect(factHeading({ kind: "fact", subject: "서아", object: undefined, attribute: "좋아하는 음료" })).toBe(
      "서아 · 좋아하는 음료",
    );
  });

  it("falls back to the subject alone when the other side is missing", () => {
    expect(factHeading({ kind: "relation", subject: "점장", object: undefined, attribute: undefined })).toBe("점장");
    expect(factHeading({ kind: "fact", subject: "서아", object: undefined, attribute: undefined })).toBe("서아");
  });
});

describe("turnRangeLabel", () => {
  it("writes a range of turns", () => {
    expect(turnRangeLabel(3, 4)).toBe("3~4번째 턴");
  });

  it("writes a single turn once", () => {
    expect(turnRangeLabel(2, 2)).toBe("2번째 턴");
  });
});

describe("itemCountLabel", () => {
  it("adds a plus while more pages remain, since there is no total", () => {
    expect(itemCountLabel(30, true)).toBe("30+");
    expect(itemCountLabel(9, false)).toBe("9");
  });
});

describe("usedInRepliesText", () => {
  it("says the memory is used in this room's replies", () => {
    expect(usedInRepliesText("episodes", true)).toBe("이 대화방의 응답에 쓰이고 있어요.");
    expect(usedInRepliesText("facts", true)).toBe("이 대화방의 응답에 쓰이고 있어요.");
  });

  it("says it is not used yet but keeps piling up", () => {
    expect(usedInRepliesText("episodes", false)).toBe("지금은 응답에 쓰이지 않아요. 장면 기억은 계속 쌓여요.");
    expect(usedInRepliesText("facts", false)).toBe("지금은 응답에 쓰이지 않아요. 사실 기억은 계속 쌓여요.");
  });
});

describe("forgetSceneTitle", () => {
  it("picks the object particle by the last syllable of the title", () => {
    expect(forgetSceneTitle("옥상에서 본 첫눈")).toBe("‘옥상에서 본 첫눈’을 잊게 할까요?");
    expect(forgetSceneTitle("비 오는 퇴근길의 우산 하나")).toBe("‘비 오는 퇴근길의 우산 하나’를 잊게 할까요?");
  });
});

describe("forgetFactConfirmLabel", () => {
  it("names the linked scenes when a secret fact takes them along", () => {
    expect(forgetFactConfirmLabel(2)).toBe("장면 2개와 함께 잊게 하기");
  });

  it("is the plain label when no scene goes with it", () => {
    expect(forgetFactConfirmLabel(0)).toBe("잊게 하기");
  });
});

describe("MEMORY_COMEBACK_NOTICE", () => {
  it("names every way a forgotten memory can come back, in the privacy policy's words", () => {
    expect(MEMORY_COMEBACK_NOTICE).toBe(
      "최근 대화나 앞으로의 대화에 같은 내용이 나오거나, 앞의 대화를 고치거나 지우거나 다시 생성하면 같은 기억이 다시 생길 수 있어요.",
    );
  });
});

describe("impressionSourceLabel", () => {
  it("counts the scenes and facts the impression was written from", () => {
    expect(impressionSourceLabel(9, 4)).toBe("장면 9개 · 사실 4개에서");
  });

  it("leaves out a kind with nothing in it", () => {
    expect(impressionSourceLabel(5, 0)).toBe("장면 5개에서");
    expect(impressionSourceLabel(0, 2)).toBe("사실 2개에서");
  });

  it("says nothing when no source is left", () => {
    expect(impressionSourceLabel(0, 0)).toBeUndefined();
  });
});
