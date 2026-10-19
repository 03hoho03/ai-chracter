import { describe, expect, it } from "vitest";

import { publishChoiceSchema, toPublishChoice } from "./publishChoiceSchema";

function parseSummary(text: string) {
  return publishChoiceSchema.safeParse({ targetOrdinal: 6, prices: [], summaries: [{ ordinal: 3, text }] });
}

describe("publishChoiceSchema 변경 요약", () => {
  it("비었거나 공백뿐이면 적어 달라고 한다", () => {
    for (const text of ["", "   \n "]) {
      const result = parseSummary(text);
      expect(result.success).toBe(false);
      expect(result.error?.issues[0]?.message).toBe("바뀐 것을 적어 주세요");
    }
  });

  it("앞뒤 공백을 덜고 100자까지 받는다", () => {
    const result = parseSummary(`  ${"가".repeat(100)}  `);
    expect(result.success).toBe(true);
    expect(result.data?.summaries[0]?.text).toBe("가".repeat(100));
  });

  it("101자는 막는다", () => {
    expect(parseSummary("가".repeat(101)).error?.issues[0]?.message).toBe("100자 이내로 적어 주세요");
  });

  it("이모지는 서버처럼 한 글자로 센다", () => {
    expect(parseSummary("😀".repeat(100)).success).toBe(true);
  });

  it("요약 칸이 없으면(꺼짐·새 화만) 검증할 것이 없다", () => {
    expect(publishChoiceSchema.safeParse({ targetOrdinal: 3, prices: [], summaries: [] }).success).toBe(true);
  });
});

describe("toPublishChoice", () => {
  it("고른 끝 화 뒤의 가격 줄은 버리고 요약은 번호로 묶는다", () => {
    expect(
      toPublishChoice({
        targetOrdinal: 7,
        prices: [
          { ordinal: 6, isFree: true },
          { ordinal: 7, isFree: false },
          { ordinal: 8, isFree: true },
        ],
        summaries: [{ ordinal: 2, text: "오타" }],
      }),
    ).toEqual({ targetOrdinal: 7, freeByOrdinal: { 6: true, 7: false }, changeSummaries: { 2: "오타" } });
  });
});
