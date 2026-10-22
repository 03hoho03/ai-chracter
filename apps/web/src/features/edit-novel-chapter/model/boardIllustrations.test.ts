import { describe, expect, it } from "vitest";

import {
  countIllustrationsInRange,
  toActiveMove,
  toIllustrationActions,
  toIllustrationLabel,
  toIllustrationSpots,
  toMovedIllustrationId,
  toMoveTarget,
  toParagraphActions,
  isUnplacedListShown,
  type BoardIllustration,
  type BoardRevision,
} from "./boardIllustrations";

function illustration(id: string, overrides: Partial<BoardIllustration> = {}): BoardIllustration {
  return {
    id,
    anchorBlockId: "b0",
    placement: "after",
    order: 0,
    assetId: `asset-${id}`,
    source: "upload",
    url: `https://img/${id}`,
    width: 300,
    height: 400,
    withheld: null,
    withheldReason: null,
    ...overrides,
  };
}

function revision(overrides: Partial<BoardRevision> = {}): BoardRevision {
  return {
    id: "r1",
    blocks: [{ id: "b0" }, { id: "b1" }, { id: "b2" }],
    illustrations: [],
    unplacedIllustrations: [],
    ...overrides,
  };
}

describe("toIllustrationSpots", () => {
  it("블록 id 를 문단 번호로 바꿔 앞·뒤 자리마다 순서대로 모은다", () => {
    const spots = toIllustrationSpots(
      revision({
        illustrations: [
          illustration("late", { anchorBlockId: "b1", placement: "after", order: 1 }),
          illustration("early", { anchorBlockId: "b1", placement: "after", order: 0 }),
          illustration("front", { anchorBlockId: "b2", placement: "before", order: 0 }),
        ],
      }),
    );
    expect(spots.after[1]?.map((item) => item.id)).toEqual(["early", "late"]);
    expect(spots.before[2]?.map((item) => item.id)).toEqual(["front"]);
    expect(spots.before[0]).toEqual([]);
    expect(spots.after[0]).toEqual([]);
  });

  it("위치 확인 필요인 그림은 문단 자리가 아니라 따로 모은다", () => {
    const spots = toIllustrationSpots(
      revision({
        unplacedIllustrations: [
          illustration("lost-b", { anchorBlockId: null, placement: null, order: 1 }),
          illustration("lost-a", { anchorBlockId: null, placement: null, order: 0 }),
        ],
      }),
    );
    expect(spots.unplaced.map((item) => item.id)).toEqual(["lost-a", "lost-b"]);
    expect(spots.after.flat()).toEqual([]);
  });

  // 스위치가 꺼졌거나 삽화 칸을 더하기 전으로 되돌린 API 는 칸이 비었거나 없다 — 본문은 지금처럼 문단만이다.
  it("삽화 칸이 없거나 빈 응답은 자리가 모두 비어 있다", () => {
    const spots = toIllustrationSpots({ id: "r1", blocks: [{ id: "b0" }] });
    expect(spots).toEqual({ before: [[]], after: [[]], unplaced: [] });
  });
});

describe("toMoveTarget", () => {
  const current = revision({
    illustrations: [
      illustration("a", { anchorBlockId: "b1", placement: "after", order: 0 }),
      illustration("b", { anchorBlockId: "b1", placement: "after", order: 1 }),
    ],
  });

  it("고른 문단의 블록 id 와 앞뒤를 보낸다", () => {
    expect(toMoveTarget(current, illustration("b", { anchorBlockId: "b1", order: 1 }), 2, "before")).toEqual({
      anchorBlockId: "b2",
      placement: "before",
    });
  });

  // 순서를 비워 보내면 그 자리 맨 끝으로 간다 — 이미 맨 끝이면 바뀌는 것 없이 판만 하나 늘어난다.
  it("지금 자리의 맨 끝이면 요청하지 않는다", () => {
    expect(
      toMoveTarget(current, illustration("b", { anchorBlockId: "b1", placement: "after", order: 1 }), 1, "after"),
    ).toBeNull();
  });

  it("같은 자리라도 맨 끝이 아니면 순서가 바뀌므로 요청한다", () => {
    expect(
      toMoveTarget(current, illustration("a", { anchorBlockId: "b1", placement: "after", order: 0 }), 1, "after"),
    ).toEqual({
      anchorBlockId: "b1",
      placement: "after",
    });
  });

  it("같은 문단의 반대쪽은 다른 자리다", () => {
    expect(
      toMoveTarget(current, illustration("b", { anchorBlockId: "b1", placement: "after", order: 1 }), 1, "before"),
    ).toEqual({
      anchorBlockId: "b1",
      placement: "before",
    });
  });

  it("위치 확인 필요인 그림은 어느 문단이든 요청한다", () => {
    expect(toMoveTarget(current, illustration("lost", { anchorBlockId: null, placement: null }), 0, "after")).toEqual({
      anchorBlockId: "b0",
      placement: "after",
    });
  });

  it("지금 판에 없는 문단이면 요청하지 않는다", () => {
    expect(toMoveTarget(current, illustration("a", { anchorBlockId: "b1" }), 7, "after")).toBeNull();
  });
});

describe("toMovedIllustrationId", () => {
  it("옮긴 자리의 맨 끝 그림이 옮긴 그림이다(판마다 배치 id 가 새로 매겨진다)", () => {
    const next = revision({
      id: "r2",
      illustrations: [
        illustration("n1", { anchorBlockId: "b2", placement: "before", order: 0 }),
        illustration("n2", { anchorBlockId: "b2", placement: "before", order: 1 }),
        illustration("n3", { anchorBlockId: "b0", placement: "after", order: 0 }),
      ],
    });
    expect(toMovedIllustrationId(next, { anchorBlockId: "b2", placement: "before" })).toBe("n2");
    expect(toMovedIllustrationId(next, { anchorBlockId: "b1", placement: "after" })).toBeUndefined();
  });
});

describe("toActiveMove", () => {
  const current = revision({
    illustrations: [illustration("a", { anchorBlockId: "b1" })],
    unplacedIllustrations: [illustration("lost", { anchorBlockId: null, placement: null })],
  });

  it("같은 판의 그림을 옮기는 중이면 그 그림이다", () => {
    expect(
      toActiveMove({ isIllustrationsOn: true, moving: { illustrationId: "a", revisionId: "r1" }, revision: current })
        ?.id,
    ).toBe("a");
    expect(
      toActiveMove({ isIllustrationsOn: true, moving: { illustrationId: "lost", revisionId: "r1" }, revision: current })
        ?.id,
    ).toBe("lost");
  });

  // 다른 곳의 수정(또는 충돌 뒤 다시 받기)으로 판이 바뀌면 배치 id 도 바뀐다. 옛 id 로 보내면 404, 옛 판으로 보내면 409 가
  // 되풀이되므로 옮기기는 그 자리에서 끝난다.
  it("판이 바뀌었으면 옮기는 중이 아니다", () => {
    expect(
      toActiveMove({ isIllustrationsOn: true, moving: { illustrationId: "a", revisionId: "r0" }, revision: current }),
    ).toBeNull();
  });

  it("그 판에 없는 그림이면 옮기는 중이 아니다", () => {
    expect(
      toActiveMove({
        isIllustrationsOn: true,
        moving: { illustrationId: "gone", revisionId: "r1" },
        revision: current,
      }),
    ).toBeNull();
  });

  it("스위치가 꺼졌으면 옮기는 중이 아니다", () => {
    expect(
      toActiveMove({ isIllustrationsOn: false, moving: { illustrationId: "a", revisionId: "r1" }, revision: current }),
    ).toBeNull();
  });
});

describe("보일 컨트롤", () => {
  // 지금 화면의 동작 줄 그대로다 — 스위치가 꺼져 있으면 옮기는 중이 될 수 없어(위 `toActiveMove`) 늘 이 목록이다.
  it("옮기는 중이 아니면 동작 줄은 지금 그대로 셋이다", () => {
    expect(toParagraphActions({ isMoving: false })).toEqual(["aiEdit", "manualEdit", "clearSelection"]);
  });

  it("옮기는 중이면 동작 줄은 앞에 놓기·뒤에 놓기·취소다", () => {
    expect(toParagraphActions({ isMoving: true })).toEqual(["placeBefore", "placeAfter", "cancelMove"]);
  });

  it.each([
    [false, true],
    [false, false],
    [true, false],
  ])("스위치 %s · 고치기 모드 %s 이면 그림 아래 조작이 없다", (isIllustrationsOn, isFixMode) => {
    expect(toIllustrationActions({ isIllustrationsOn, isFixMode, illustration: illustration("a") })).toEqual([]);
  });

  it("켜짐·고치기 모드면 옮기기·떼기", () => {
    expect(
      toIllustrationActions({ isIllustrationsOn: true, isFixMode: true, illustration: illustration("a") }),
    ).toEqual(["move", "detach"]);
  });

  // 내린 그림은 독자에게 안내 상자로만 서고, 그대로 두면 이 화를 다시 공개할 수 없다 — 할 일은 떼기뿐이다.
  it("운영자가 내린 그림은 떼기만", () => {
    expect(
      toIllustrationActions({
        isIllustrationsOn: true,
        isFixMode: true,
        illustration: illustration("a", { withheld: "taken_down" }),
      }),
    ).toEqual(["detach"]);
  });

  it("원작이 이용 제한 중인 그림은 풀릴 수 있어 옮기기도 둔다", () => {
    expect(
      toIllustrationActions({
        isIllustrationsOn: true,
        isFixMode: true,
        illustration: illustration("a", { withheld: "original_restricted" }),
      }),
    ).toEqual(["move", "detach"]);
  });

  it("위치 확인 필요 목록은 스위치가 켜져 있고 그런 그림이 있을 때만", () => {
    const withLost = revision({
      unplacedIllustrations: [illustration("lost", { anchorBlockId: null, placement: null })],
    });
    expect(isUnplacedListShown({ isIllustrationsOn: true, revision: withLost })).toBe(true);
    expect(isUnplacedListShown({ isIllustrationsOn: false, revision: withLost })).toBe(false);
    expect(isUnplacedListShown({ isIllustrationsOn: true, revision: revision() })).toBe(false);
    expect(isUnplacedListShown({ isIllustrationsOn: true, revision: { id: "r1", blocks: [] } })).toBe(false);
  });
});

describe("toIllustrationLabel", () => {
  it("자리를 사람의 말로, 같은 자리에 여럿이면 몇째인지 붙인다", () => {
    expect(toIllustrationLabel({ paragraphIndex: 2, placement: "after", rank: 0, count: 1 })).toBe(
      "3번째 문단 뒤 삽화",
    );
    expect(toIllustrationLabel({ paragraphIndex: 0, placement: "before", rank: 1, count: 2 })).toBe(
      "1번째 문단 앞 삽화 2",
    );
  });
});

describe("countIllustrationsInRange", () => {
  it("직접 고치는 범위 문단의 앞·뒤 그림 수", () => {
    const spots = toIllustrationSpots(
      revision({
        illustrations: [
          illustration("a", { anchorBlockId: "b0", placement: "after" }),
          illustration("b", { anchorBlockId: "b1", placement: "before" }),
          illustration("c", { anchorBlockId: "b2", placement: "after" }),
        ],
      }),
    );
    expect(countIllustrationsInRange(spots, { start: 1, end: 2 })).toBe(2);
    expect(countIllustrationsInRange(spots, { start: 0, end: 0 })).toBe(1);
  });
});
