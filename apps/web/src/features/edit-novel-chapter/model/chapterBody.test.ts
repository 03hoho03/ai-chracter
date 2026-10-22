import { describe, expect, it } from "vitest";

import {
  assembleChapterBody,
  countChapterChars,
  inheritBlockIds,
  isManualEditStale,
  joinParagraphRange,
  splitChapterParagraphs,
  toAiEditComparison,
  toManualEditSave,
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

/** 응답의 판 모양(`id`·`paragraphs`·`blocks`)으로 판 하나를 만든다. 블록 id 는 `글자@판` 꼴로 지어 어느 판의 id 인지 보인다. */
function revisionOf(id: string, paragraphs: string[], blockIds = paragraphs.map((_, index) => `b${index}@${id}`)) {
  return { id, paragraphs, blocks: blockIds.map((blockId) => ({ id: blockId })) };
}

describe("toManualEditSave", () => {
  // 고치기를 시작한 판. 이용자는 둘째 문단을 고치고 있다.
  const started = revisionOf("r1", ["하나", "둘", "셋"]);
  const base = {
    revisionId: "r1",
    paragraphs: started.paragraphs,
    blockIds: started.blocks.map((block) => block.id),
    range: { start: 1, end: 1 },
  };
  // 입력칸이 열린 동안 다른 탭이 맨 앞에 문단을 넣고 셋째 문단을 고쳐 새 판 r2 가 됐다.
  const newer = revisionOf("r2", ["머리말", "하나", "둘", "다른 탭이 고친 셋"]);

  it("지금 보이는 판으로 조립하면 다른 탭이 고친 글이 조용히 덮인다", () => {
    // 고치기 전의 저장 방식: 지금 캐시의 문단·판으로 조립하고 그 판을 기준으로 보낸다 — 서버는 기준이 최신이라 받아들인다.
    const body = assembleChapterBody(newer.paragraphs, base.range, "새 둘");
    expect(body).toBe("머리말\n\n새 둘\n\n둘\n\n다른 탭이 고친 셋");
    expect(body).not.toContain("하나");
  });

  it("고치기를 시작한 판의 문단으로 조립하고 그 판을 기준으로 보낸다 — 판이 바뀌었으면 서버가 충돌로 막는다", () => {
    expect(toManualEditSave(base, "새 둘", newer)).toEqual({
      baseRevisionId: "r1",
      body: "하나\n\n새 둘\n\n셋",
      blockIds: ["b0@r1", "b1@r1", "b2@r1"],
      isUnchanged: false,
    });
    expect(toManualEditSave(base, "새 둘", newer).baseRevisionId).not.toBe(newer.id);
  });

  it("시작한 판과 같은 글이면 바뀐 것이 없다", () => {
    expect(toManualEditSave(base, "둘", started).isUnchanged).toBe(true);
  });

  it("그사이 같은 글·같은 블록의 새 판(삽화만 바꾼 판)이 생겼으면 그 판을 기준으로 보낸다", () => {
    const illustrated = revisionOf("r2", ["하나", "둘", "셋"], base.blockIds);
    expect(toManualEditSave(base, "새 둘", illustrated)).toEqual({
      baseRevisionId: "r2",
      body: "하나\n\n새 둘\n\n셋",
      blockIds: ["b0@r1", "b1@r1", "b2@r1"],
      isUnchanged: false,
    });
  });

  it("글은 같아도 블록이 다른 판(옛 판으로 되돌린 판)이면 시작한 판을 기준으로 보낸다", () => {
    const reverted = revisionOf("r3", ["하나", "둘", "셋"]);
    expect(toManualEditSave(base, "새 둘", reverted).baseRevisionId).toBe("r1");
  });

  it("범위 밖 문단은 제자리 id 를 싣는다 — 범위 가장자리에 바깥 문단과 같은 글을 새로 써도 바깥 id 가 옮겨 가지 않는다", () => {
    const scene = revisionOf("r1", ["* * *", "가", "* * *", "나"]);
    const sceneBase = {
      revisionId: "r1",
      paragraphs: scene.paragraphs,
      blockIds: scene.blocks.map((block) => block.id),
      range: { start: 1, end: 1 },
    };
    // 둘째 문단 "가" 를 "가\n\n* * *" 로 고쳐 범위 끝에 바깥 셋째 문단과 같은 글을 새로 썼다.
    const save = toManualEditSave(sceneBase, "가\n\n* * *", scene);
    expect(save.body).toBe("* * *\n\n가\n\n* * *\n\n* * *\n\n나");
    expect(save.blockIds).toEqual(["b0@r1", "b1@r1", null, "b2@r1", "b3@r1"]);
  });

  it("범위를 모두 지우면 그 문단 id 만 빠진다", () => {
    expect(toManualEditSave(base, "", started).blockIds).toEqual(["b0@r1", "b2@r1"]);
  });

  it("블록 id 수는 늘 본문 문단 수와 같고 겹치지 않는다", () => {
    const drafts = ["", "둘", "새 둘", "둘\n\n둘", "앞\n\n둘\n\n뒤", "하나\n\n셋", "  \n\n 둘 \n\n\n"];
    for (const draft of drafts) {
      const save = toManualEditSave(base, draft, started);
      expect(save.blockIds).toHaveLength(splitChapterParagraphs(save.body).length);
      const sent = save.blockIds.filter((id) => id !== null);
      expect(new Set(sent).size).toBe(sent.length);
    }
  });
});

describe("isManualEditStale", () => {
  const base = { revisionId: "r1", paragraphs: ["하나", "둘"], blockIds: ["a", "b"], range: { start: 0, end: 0 } };

  it("시작한 판 그대로면 낡지 않았다", () => {
    expect(isManualEditStale(base, revisionOf("r1", ["하나", "둘"], ["a", "b"]))).toBe(false);
  });

  it("같은 글·같은 블록의 새 판이면 낡지 않았다", () => {
    expect(isManualEditStale(base, revisionOf("r2", ["하나", "둘"], ["a", "b"]))).toBe(false);
  });

  it("같은 글이지만 블록이 다른 판이면 낡았다", () => {
    expect(isManualEditStale(base, revisionOf("r2", ["하나", "둘"], ["x", "y"]))).toBe(true);
  });

  it("글이 바뀐 판이면 낡았다", () => {
    expect(isManualEditStale(base, revisionOf("r2", ["하나", "둘 고침"], ["a", "b"]))).toBe(true);
  });
});

describe("inheritBlockIds", () => {
  const ids = ["a", "b", "c"];

  it("같은 글 문단은 id 를 잇는다", () => {
    expect(inheritBlockIds(["가", "나", "다"], ids, ["가", "나", "다"])).toEqual(["a", "b", "c"]);
  });

  it("바뀐 구간의 첫 새 문단이 그 구간 첫 옛 id 를 잇고 나머지는 새 문단이다", () => {
    expect(inheritBlockIds(["가", "나", "다"], ids, ["가", "나1", "나2", "다"])).toEqual(["a", "b", null, "c"]);
  });

  it("끼워 넣은 문단은 새 문단이고 지운 문단의 id 는 빠진다", () => {
    expect(inheritBlockIds(["가", "나", "다"], ids, ["새", "가", "다"])).toEqual([null, "a", "c"]);
  });

  it("범위 안이 모두 바뀌면 첫 문단만 잇는다", () => {
    expect(inheritBlockIds(["가", "나"], ["a", "b"], ["x", "y", "z"])).toEqual(["a", null, null]);
  });

  it("비면 빈 목록이다", () => {
    expect(inheritBlockIds(["가"], ["a"], [])).toEqual([]);
    expect(inheritBlockIds([], [], ["가"])).toEqual([null]);
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
