import { describe, expect, it } from "vitest";

import { isIllustrationOnlyChange, shouldWarnPendingAiEditsLost, type ComparableRevision } from "./revisionComparison";

type Illustration = ComparableRevision["illustrations"][number];

function picture(overrides: Partial<Illustration> = {}): Illustration {
  return {
    anchorBlockId: "a1",
    placement: "after",
    order: 0,
    assetId: "asset-1",
    source: "upload",
    ...overrides,
  };
}

/** 문단 `paragraphs`, 블록 id `prefix+순번` 의 판. */
function revision(
  paragraphs: string[],
  illustrations: Illustration[] = [],
  { prefix = "a", unplaced = [] as Illustration[] } = {},
): ComparableRevision {
  return {
    paragraphs,
    blocks: paragraphs.map((_, index) => ({ id: `${prefix}${index}` })),
    illustrations,
    unplacedIllustrations: unplaced,
  };
}

describe("isIllustrationOnlyChange", () => {
  const text = ["하나", "둘"];

  it("글이 같고 그림이 다르면 삽화만 바뀌었다", () => {
    expect(isIllustrationOnlyChange(revision(text), revision(text, [picture()]))).toBe(true);
    expect(isIllustrationOnlyChange(revision(text, [picture()]), revision(text, [picture({ assetId: "asset-2" })]))).toBe(
      true,
    );
    expect(isIllustrationOnlyChange(revision(text, [picture()]), revision(text, [picture({ placement: "before" })]))).toBe(
      true,
    );
    expect(isIllustrationOnlyChange(revision(text, [picture()]), revision(text, [picture({ anchorBlockId: "a0" })]))).toBe(
      true,
    );
    expect(isIllustrationOnlyChange(revision(text, [picture()]), revision(text, [picture({ source: "generated" })]))).toBe(
      true,
    );
  });

  it("위치 확인이 필요한 그림이 생기거나 빠져도 삽화가 바뀐 것이다", () => {
    const lost = picture({ anchorBlockId: null, placement: null });
    expect(isIllustrationOnlyChange(revision(text, [], { unplaced: [lost] }), revision(text))).toBe(true);
  });

  it("같은 자리 두 그림의 순서가 바뀌면 삽화가 바뀐 것이다", () => {
    const first = picture({ assetId: "x", order: 0 });
    const second = picture({ assetId: "y", order: 1 });
    expect(
      isIllustrationOnlyChange(
        revision(text, [first, second]),
        revision(text, [
          { ...first, order: 1 },
          { ...second, order: 0 },
        ]),
      ),
    ).toBe(true);
  });

  it("블록 id·순서 값만 다르고 화면이 같으면(되돌린 판) 바뀐 것이 없다", () => {
    expect(
      isIllustrationOnlyChange(
        revision(text, [picture({ anchorBlockId: "a1", order: 0 })]),
        revision(text, [picture({ anchorBlockId: "z1", order: 5 })], { prefix: "z" }),
      ),
    ).toBe(false);
  });

  it("글이 바뀌었으면 글 비교가 맡는다", () => {
    expect(isIllustrationOnlyChange(revision(text), revision(["하나", "둘 고침"], [picture()]))).toBe(false);
  });

  it("그림이 없는 두 판(삽화 스위치가 꺼진 응답)은 지금과 같다 — 글 비교가 맡는다", () => {
    expect(isIllustrationOnlyChange(revision(text), revision(text))).toBe(false);
    expect(isIllustrationOnlyChange(revision(text), revision(["다른 글"]))).toBe(false);
  });
});

describe("shouldWarnPendingAiEditsLost", () => {
  const same = { paragraphs: ["하나", "둘"] };

  it("되돌릴 판 글이 지금 글과 같으면 수정안이 남으니 말하지 않는다", () => {
    expect(shouldWarnPendingAiEditsLost({ hasPendingAiEdits: true, target: same, current: { paragraphs: ["하나", "둘"] } })).toBe(
      false,
    );
  });

  it("글이 다르면 사라진다고 말한다", () => {
    expect(shouldWarnPendingAiEditsLost({ hasPendingAiEdits: true, target: same, current: { paragraphs: ["하나"] } })).toBe(true);
  });

  it("두 판 글을 아직 모르면 말한다", () => {
    expect(shouldWarnPendingAiEditsLost({ hasPendingAiEdits: true, target: undefined, current: same })).toBe(true);
    expect(shouldWarnPendingAiEditsLost({ hasPendingAiEdits: true, target: same, current: undefined })).toBe(true);
  });

  it("수정안이 없으면 말하지 않는다", () => {
    expect(shouldWarnPendingAiEditsLost({ hasPendingAiEdits: false, target: same, current: { paragraphs: ["다른"] } })).toBe(
      false,
    );
  });
});
