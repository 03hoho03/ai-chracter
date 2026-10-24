import { describe, expect, it } from "vitest";

import { editConfirmStatNote, statRewindNotice } from "./statRewindNotice";

const STATS = { hasStats: true, hasReachedEnding: false };
const STATS_ENDED = { hasStats: true, hasReachedEnding: true };

describe("statRewindNotice", () => {
  it("says nothing when the server reported nothing to tell (user message, opening, character room, older server)", () => {
    expect(statRewindNotice("delete", undefined, STATS)).toBeUndefined();
    expect(statRewindNotice("edit", undefined, STATS_ENDED)).toBeUndefined();
  });

  // 서버는 스탯이 없거나 숨긴 스탯뿐인 스토리 방에도 값을 보낸다. 보이는 스탯이 없는 방에서 띄우면 잡음이고, 숨긴 스탯이
  // 있다는 것을 드러낸다.
  it("says nothing in a room with no visible stats, whatever the server reported", () => {
    for (const statRewind of ["rewound", "partial", "kept"] as const) {
      expect(statRewindNotice("delete", statRewind, { hasStats: false, hasReachedEnding: true })).toBeUndefined();
      expect(statRewindNotice("edit", statRewind, { hasStats: false, hasReachedEnding: false })).toBeUndefined();
    }
  });

  it("tells that deleting the last reply put the stats back", () => {
    expect(statRewindNotice("delete", "rewound", STATS)).toBe("메시지를 지웠어요. 스탯도 그 답 전으로 되돌렸어요.");
  });

  it("adds that a seen ending stays, only in a room that reached one", () => {
    expect(statRewindNotice("delete", "rewound", STATS_ENDED)).toBe(
      "메시지를 지웠어요. 스탯도 그 답 전으로 되돌렸어요. 이미 본 엔딩은 그대로예요.",
    );
    expect(statRewindNotice("edit", "rewound", STATS_ENDED)).toBe(
      "메시지를 고쳤어요. 스탯을 고친 턴 전으로 되돌렸고, 이미 본 엔딩은 그대로예요.",
    );
  });

  it("tells that an edit put the stats back to before the removed turns", () => {
    expect(statRewindNotice("edit", "rewound", STATS)).toBe("메시지를 고쳤어요. 스탯도 고친 턴 전으로 되돌렸어요.");
  });

  // 남긴 이유를 대지 않는다 — 중간 답 삭제만이 아니라 옛 삭제가 턴 수를 어긋나게 둔 방의 마지막 답도 여기로 온다.
  it("says plainly that the stats stay when the server kept them", () => {
    expect(statRewindNotice("delete", "kept", STATS_ENDED)).toBe("메시지를 지웠어요. 스탯은 되돌리지 않아요.");
    expect(statRewindNotice("edit", "kept", STATS)).toBe("메시지를 고쳤어요. 스탯은 되돌리지 않아요.");
  });

  it("tells that old turns without a record were not rewound", () => {
    expect(statRewindNotice("delete", "partial", STATS)).toBe(
      "메시지를 지웠어요. 오래된 대화라 이 답의 스탯은 되돌리지 못했어요.",
    );
    expect(statRewindNotice("edit", "partial", STATS)).toBe(
      "메시지를 고쳤어요. 오래된 대화가 섞여 있어 그 부분의 스탯은 되돌리지 못했어요.",
    );
  });
});

describe("editConfirmStatNote", () => {
  it("has no line in a room with no visible stats", () => {
    expect(editConfirmStatNote({ hasStats: false, hasReachedEnding: true })).toBeUndefined();
  });

  it("tells the stats go back to before the removed turns", () => {
    expect(editConfirmStatNote(STATS)).toBe("스탯은 지워지는 대화 전으로 돌아가요.");
  });

  // 토스트와 같은 규칙 — 엔딩 문장은 엔딩을 본 방에만.
  it("adds that a seen ending stays, only in a room that reached one", () => {
    expect(editConfirmStatNote(STATS_ENDED)).toBe("스탯은 지워지는 대화 전으로 돌아가요. 이미 본 엔딩은 그대로예요.");
  });
});
