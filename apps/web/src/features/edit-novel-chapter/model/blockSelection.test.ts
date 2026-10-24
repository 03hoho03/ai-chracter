import { describe, expect, it } from "vitest";

import {
  formatParagraphIndexes,
  nextBlockSelection,
  toBlockBlockedReason,
  toBlockSelectionAnnouncement,
  toBlockSelectionLabel,
  toContiguousRange,
  toReleaseOnSwitchOff,
  toSceneKeyOf,
  toSelectedIndexes,
  withObjectParticle,
  type BlockSelectionContext,
} from "./blockSelection";

const BLOCKS = ["b0", "b1", "b2", "b3", "b4", "b5", "b6"];

/** b0~b3 은 장면 s1, b4~b6 은 장면 s2. */
const twoScenes = toSceneKeyOf({
  blocks: BLOCKS.map((id) => ({ id })),
  scenes: [
    { id: "s1", title: "문 앞", blockIds: ["b0", "b1", "b2", "b3"] },
    { id: "s2", title: "회랑", blockIds: ["b4", "b5", "b6"] },
  ],
});

function context(extra: Partial<BlockSelectionContext> = {}): BlockSelectionContext {
  return { blockIds: BLOCKS, sceneKeyOf: twoScenes, maxBlocks: 20, isSelectable: () => true, ...extra };
}

describe("toSceneKeyOf", () => {
  // 장면 경계가 없는 화(옛 흐름 원고)는 화 전체가 한 장면이다.
  it("장면 목록이 비면 모든 블록이 같은 장면이다", () => {
    const sceneOf = toSceneKeyOf({ blocks: BLOCKS.map((id) => ({ id })), scenes: [] });
    expect(new Set(BLOCKS.map(sceneOf)).size).toBe(1);
  });

  it("장면마다 그 블록들이 같은 열쇠를 갖는다", () => {
    expect(twoScenes("b0")).toBe(twoScenes("b3"));
    expect(twoScenes("b3")).not.toBe(twoScenes("b4"));
  });

  // 서버가 모든 블록을 장면에 넣어 주지만, 빠진 블록이 오면 어느 장면과도 묶지 않는다(서버 422 를 미리 막는 쪽).
  it("장면 목록에 없는 블록은 혼자다", () => {
    expect(twoScenes("unknown")).not.toBe(twoScenes("b0"));
    expect(twoScenes("unknown")).not.toBe(twoScenes("other-unknown"));
  });
});

describe("nextBlockSelection", () => {
  it("누르면 켜고, 다시 누르면 끈다 — 떨어진 문단도 함께 고른다", () => {
    let step = nextBlockSelection([], 0, {}, context());
    expect(step).toEqual({ selection: ["b0"], outcome: "added" });
    step = nextBlockSelection(step.selection, 2, {}, context());
    expect(step).toEqual({ selection: ["b0", "b2"], outcome: "added" });
    step = nextBlockSelection(step.selection, 0, {}, context());
    expect(step).toEqual({ selection: ["b2"], outcome: "removed" });
  });

  it("다른 장면의 문단은 고르지 않는다", () => {
    expect(nextBlockSelection(["b1"], 5, {}, context())).toEqual({ selection: ["b1"], outcome: "outsideScene" });
  });

  it("다 풀면 어느 장면이든 새로 고를 수 있다", () => {
    expect(nextBlockSelection([], 5, {}, context())).toEqual({ selection: ["b5"], outcome: "added" });
  });

  it("상한만큼 골랐으면 더 고르지 않는다", () => {
    expect(nextBlockSelection(["b0", "b1"], 2, {}, context({ maxBlocks: 2 }))).toEqual({
      selection: ["b0", "b1"],
      outcome: "limit",
    });
  });

  it("상한에 닿아도 고른 문단을 끄는 것은 된다", () => {
    expect(nextBlockSelection(["b0", "b1"], 1, {}, context({ maxBlocks: 2 }))).toEqual({
      selection: ["b0"],
      outcome: "removed",
    });
  });

  it("고를 수 없는 문단(수정안이 놓인 자리)은 바꾸지 않는다", () => {
    const step = nextBlockSelection(["b0"], 2, {}, context({ isSelectable: (index) => index !== 2 }));
    expect(step.selection).toEqual(["b0"]);
  });

  describe("Shift 이어 고르기", () => {
    it("마지막으로 고른 문단부터 누른 문단까지 같은 장면 안을 모두 켠다", () => {
      expect(nextBlockSelection(["b0"], 3, { extend: true }, context())).toEqual({
        selection: ["b0", "b1", "b2", "b3"],
        outcome: "added",
      });
    });

    it("거꾸로도 이어 고르고, 이미 고른 문단은 끄지 않는다", () => {
      expect(nextBlockSelection(["b1", "b3"], 0, { extend: true }, context())).toEqual({
        selection: ["b1", "b3", "b2", "b0"],
        outcome: "added",
      });
    });

    it("누른 문단이 다른 장면이면 하나도 켜지 않는다", () => {
      expect(nextBlockSelection(["b2"], 5, { extend: true }, context())).toEqual({
        selection: ["b2"],
        outcome: "outsideScene",
      });
    });

    it("고를 수 없는 문단은 건너뛴다", () => {
      const step = nextBlockSelection(["b0"], 3, { extend: true }, context({ isSelectable: (index) => index !== 2 }));
      expect(step.selection).toEqual(["b0", "b1", "b3"]);
    });

    it("상한에 닿으면 거기까지만 켜고 상한을 알린다", () => {
      expect(nextBlockSelection(["b0"], 3, { extend: true }, context({ maxBlocks: 3 }))).toEqual({
        selection: ["b0", "b1", "b2"],
        outcome: "limit",
      });
    });

    it("고른 것이 없으면 그 문단 하나를 켠다", () => {
      expect(nextBlockSelection([], 4, { extend: true }, context())).toEqual({ selection: ["b4"], outcome: "added" });
    });
  });
});

describe("toSelectedIndexes", () => {
  it("본문 차례로 돌려주고, 지금 판에 없는 블록은 뺀다", () => {
    expect(toSelectedIndexes(["b5", "gone", "b4"], BLOCKS)).toEqual([4, 5]);
  });
});

describe("toBlockBlockedReason", () => {
  it("고른 것이 없으면 막지 않는다", () => {
    expect(toBlockBlockedReason(5, [], context())).toBeUndefined();
  });

  it("다른 장면의 문단은 장면 때문에 막힌다", () => {
    expect(toBlockBlockedReason(5, ["b0"], context())).toBe("outsideScene");
    expect(toBlockBlockedReason(1, ["b0"], context())).toBeUndefined();
  });

  it("상한만큼 골랐으면 고르지 않은 문단은 상한 때문에 막히고 고른 문단은 막히지 않는다", () => {
    expect(toBlockBlockedReason(2, ["b0", "b1"], context({ maxBlocks: 2 }))).toBe("limit");
    expect(toBlockBlockedReason(1, ["b0", "b1"], context({ maxBlocks: 2 }))).toBeUndefined();
  });
});

describe("문장", () => {
  it("이어진 문단은 물결로 접고 떨어진 문단은 가운뎃점으로 잇는다", () => {
    expect(formatParagraphIndexes([2])).toBe("3번째 문단");
    expect(formatParagraphIndexes([2, 4, 6])).toBe("3·5·7번째 문단");
    expect(formatParagraphIndexes([1, 2, 3, 6])).toBe("2~4·7번째 문단");
  });

  it("둘 이상이면 개수를 붙인다", () => {
    expect(toBlockSelectionLabel([2])).toBe("3번째 문단");
    expect(toBlockSelectionLabel([2, 4, 6])).toBe("3·5·7번째 문단 3개");
  });

  it("알림 문장은 고른 것과 막힌 까닭을 말한다", () => {
    expect(toBlockSelectionAnnouncement([], "removed", 20)).toBe("고른 문단이 없어요.");
    expect(toBlockSelectionAnnouncement([2], "added", 20)).toBe("3번째 문단을 골랐어요.");
    expect(toBlockSelectionAnnouncement([2, 4, 6], "added", 20)).toBe("3·5·7번째 문단, 3개를 골랐어요.");
    expect(toBlockSelectionAnnouncement([2], "outsideScene", 20)).toBe("같은 장면 안의 문단만 함께 고를 수 있어요.");
    expect(toBlockSelectionAnnouncement([0, 1], "limit", 2)).toBe(
      "1~2번째 문단, 2개를 골랐어요. 한 번에 2개 문단까지 고를 수 있어요.",
    );
  });

  it("목적격 조사는 받침에 맞춘다", () => {
    expect(withObjectParticle("3~5번째 문단")).toBe("3~5번째 문단을");
    expect(withObjectParticle("3·5번째 문단 2개")).toBe("3·5번째 문단 2개를");
  });
});

describe("toContiguousRange", () => {
  it("이어진 문단이면 범위, 떨어졌거나 비었으면 없다", () => {
    expect(toContiguousRange([2, 3, 4])).toEqual({ start: 2, end: 4 });
    expect(toContiguousRange([3])).toEqual({ start: 3, end: 3 });
    expect(toContiguousRange([2, 4])).toBeNull();
    expect(toContiguousRange([])).toBeNull();
  });
});

// 여러 문단 수정 요청이 스위치 꺼짐(404)으로 거절되면 가격을 다시 받아 고르기가 거둬진다. 그때 고른 것을 "선택 해제"처럼 풀어야
// 상태 줄이 지난 고르기를 말하지 않고, 사라진 동작 줄 대신 둘 포커스 자리가 생긴다.
describe("toReleaseOnSwitchOff", () => {
  it("켜졌다가 꺼졌고 고른 문단이 있으면 본문 차례로 마지막 고른 문단에 포커스를 둔다", () => {
    expect(toReleaseOnSwitchOff({ wasOn: true, isOn: false, selection: ["b4", "b1", "b2"], blockIds: BLOCKS })).toEqual({
      focusIndex: 4,
    });
  });

  it("고른 것이 없거나(지금 판에 없는 블록뿐이어도) 스위치가 그대로면 풀 것이 없다", () => {
    expect(toReleaseOnSwitchOff({ wasOn: true, isOn: false, selection: [], blockIds: BLOCKS })).toBeUndefined();
    expect(toReleaseOnSwitchOff({ wasOn: true, isOn: false, selection: ["gone"], blockIds: BLOCKS })).toBeUndefined();
    expect(toReleaseOnSwitchOff({ wasOn: true, isOn: true, selection: ["b1"], blockIds: BLOCKS })).toBeUndefined();
    expect(toReleaseOnSwitchOff({ wasOn: false, isOn: false, selection: ["b1"], blockIds: BLOCKS })).toBeUndefined();
    expect(toReleaseOnSwitchOff({ wasOn: false, isOn: true, selection: ["b1"], blockIds: BLOCKS })).toBeUndefined();
  });
});
