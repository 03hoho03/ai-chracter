import { describe, expect, it } from "vitest";

import { summaryRevertHint } from "./summaryRevertHint";

describe("summaryRevertHint", () => {
  it("keeps today's sentence while regeneration is not offered", () => {
    expect(summaryRevertHint(false)).toBe("되돌리기는 직접 고친 내용만 돼요. AI가 다시 정리한 요약은 되돌릴 수 없어요.");
  });

  it("says revert goes back once to the text before the last edit or regeneration once regeneration exists", () => {
    expect(summaryRevertHint(true)).toBe("되돌리기는 마지막으로 고치거나 다시 만들기 전의 글로 한 번 돌아가요.");
  });
});
