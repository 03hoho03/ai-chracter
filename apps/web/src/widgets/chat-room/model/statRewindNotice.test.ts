import { describe, expect, it } from "vitest";

import { statRewindNotice } from "./statRewindNotice";

describe("statRewindNotice", () => {
  it("says nothing when the server reported nothing to tell (user message, opening, character room, older server)", () => {
    expect(statRewindNotice("delete", undefined, false)).toBeUndefined();
    expect(statRewindNotice("edit", undefined, true)).toBeUndefined();
  });

  it("tells that deleting the last reply put the stats back", () => {
    expect(statRewindNotice("delete", "rewound", false)).toBe("메시지를 지웠어요. 스탯도 그 답 전으로 되돌렸어요.");
  });

  it("adds that a seen ending stays, only in a room that reached one", () => {
    expect(statRewindNotice("delete", "rewound", true)).toBe(
      "메시지를 지웠어요. 스탯도 그 답 전으로 되돌렸어요. 이미 본 엔딩은 그대로예요.",
    );
    expect(statRewindNotice("edit", "rewound", true)).toBe(
      "메시지를 고쳤어요. 스탯을 고친 턴 전으로 되돌렸고, 이미 본 엔딩은 그대로예요.",
    );
  });

  it("tells that an edit put the stats back to before the removed turns", () => {
    expect(statRewindNotice("edit", "rewound", false)).toBe("메시지를 고쳤어요. 스탯도 고친 턴 전으로 되돌렸어요.");
  });

  // 남긴 이유를 대지 않는다 — 중간 답 삭제만이 아니라 옛 삭제가 턴 수를 어긋나게 둔 방의 마지막 답도 여기로 온다.
  it("says plainly that the stats stay when the server kept them", () => {
    expect(statRewindNotice("delete", "kept", true)).toBe("메시지를 지웠어요. 스탯은 되돌리지 않아요.");
    expect(statRewindNotice("edit", "kept", false)).toBe("메시지를 고쳤어요. 스탯은 되돌리지 않아요.");
  });

  it("tells that old turns without a record were not rewound", () => {
    expect(statRewindNotice("delete", "partial", false)).toBe(
      "메시지를 지웠어요. 오래된 대화라 이 답의 스탯은 되돌리지 못했어요.",
    );
    expect(statRewindNotice("edit", "partial", false)).toBe(
      "메시지를 고쳤어요. 오래된 대화가 섞여 있어 그 부분의 스탯은 되돌리지 못했어요.",
    );
  });
});
