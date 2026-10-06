import { describe, expect, it } from "vitest";

import { statRemovalConfirmDescription } from "./statRemovalConfirm";

describe("statRemovalConfirmDescription", () => {
  it("엔딩 조건만 걸리면 상황 노트가 생기기 전과 같은 문장이다", () => {
    expect(statRemovalConfirmDescription({ endingRuleCount: 2, noteRuleCount: 0, emptiedNoteCount: 0, priorityEndingCount: 0 })).toBe(
      "이 스탯을 쓰는 엔딩 조건 2개도 함께 지워져요.",
    );
  });

  it("상황 노트 조건만 걸리면 노트 조건 수를 센다", () => {
    expect(statRemovalConfirmDescription({ endingRuleCount: 0, noteRuleCount: 3, emptiedNoteCount: 0, priorityEndingCount: 0 })).toBe(
      "이 스탯을 쓰는 상황 노트 조건 3개도 함께 지워져요.",
    );
  });

  it("둘 다 걸리면 한 문장에 함께 센다", () => {
    expect(statRemovalConfirmDescription({ endingRuleCount: 2, noteRuleCount: 3, emptiedNoteCount: 0, priorityEndingCount: 0 })).toBe(
      "이 스탯을 쓰는 엔딩 조건 2개와 상황 노트 조건 3개도 함께 지워져요.",
    );
  });

  it("조건이 모두 사라지는 노트가 있으면 발행 전에 다시 넣어야 한다고 덧붙인다", () => {
    expect(statRemovalConfirmDescription({ endingRuleCount: 1, noteRuleCount: 1, emptiedNoteCount: 1, priorityEndingCount: 0 })).toBe(
      "이 스탯을 쓰는 엔딩 조건 1개와 상황 노트 조건 1개도 함께 지워져요. 조건이 모두 사라지는 상황 노트 1개는 조건을 다시 넣어야 발행할 수 있어요.",
    );
  });

  it("이 스탯을 우선순위 스탯으로 고른 엔딩이 있으면 그 칸이 비워진다고 덧붙인다", () => {
    expect(
      statRemovalConfirmDescription({ endingRuleCount: 1, noteRuleCount: 1, emptiedNoteCount: 1, priorityEndingCount: 2 }),
    ).toBe(
      "이 스탯을 쓰는 엔딩 조건 1개와 상황 노트 조건 1개도 함께 지워져요. 조건이 모두 사라지는 상황 노트 1개는 조건을 다시 넣어야 발행할 수 있어요. 이 스탯을 우선순위 스탯으로 고른 엔딩 2개는 우선순위 스탯이 ‘없음’으로 바뀌어요.",
    );
  });
});
