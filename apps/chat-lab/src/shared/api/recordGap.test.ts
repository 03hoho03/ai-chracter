import { describe, expect, it } from "vitest";

import { runRecordGap } from "./recordGap";

describe("runRecordGap", () => {
  it("이전 형식은 턴 기록 파일이 있어도 없어도 이전 형식 — 내보내라고 하지 않는다", () => {
    expect(runRecordGap({ format: "preMessageId", hasChatTurns: true })).toBe("oldFormat");
    expect(runRecordGap({ format: "preMessageId", hasChatTurns: false })).toBe("oldFormat");
  });

  it("현행 형식은 파일이 없으면 내보내기 필요, 있으면 런 전체의 빈칸이 아니다", () => {
    expect(runRecordGap({ format: "current", hasChatTurns: false })).toBe("needsExport");
    expect(runRecordGap({ format: "current", hasChatTurns: true })).toBeUndefined();
  });
});
