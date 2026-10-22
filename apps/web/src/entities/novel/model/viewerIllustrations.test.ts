import { describe, expect, it } from "vitest";

import { toOwnerViewerIllustrations, toPublicViewerIllustrations, type OwnerIllustration } from "./viewerIllustrations";

const BLOCKS = [{ id: "block-a" }, { id: "block-b" }, { id: "block-c" }];

function ownerIllustration(overrides: Partial<OwnerIllustration> = {}): OwnerIllustration {
  return {
    anchorBlockId: "block-b",
    placement: "before",
    order: 0,
    source: "upload",
    url: "https://cdn.example/a.webp",
    width: 768,
    height: 1024,
    withheld: null,
    withheldReason: null,
    ...overrides,
  };
}

describe("toOwnerViewerIllustrations", () => {
  it("turns the anchor block id into the paragraph index of the same revision", () => {
    expect(toOwnerViewerIllustrations({ blocks: BLOCKS, illustrations: [ownerIllustration({ placement: "after", order: 2 })] })).toEqual([
      {
        paragraphIndex: 1,
        placement: "after",
        order: 2,
        source: "upload",
        url: "https://cdn.example/a.webp",
        width: 768,
        height: 1024,
        withheld: null,
        withheldReason: null,
      },
    ]);
  });

  it("keeps the withheld placeholder the reader screen also shows", () => {
    const [placed] = toOwnerViewerIllustrations({
      blocks: BLOCKS,
      illustrations: [ownerIllustration({ url: null, withheld: "taken_down", withheldReason: "사유" })],
    });
    expect(placed).toMatchObject({ url: null, withheld: "taken_down", withheldReason: "사유" });
  });

  it("leaves out an illustration whose anchor is unknown or gone", () => {
    expect(
      toOwnerViewerIllustrations({
        blocks: BLOCKS,
        illustrations: [ownerIllustration({ anchorBlockId: null, placement: null }), ownerIllustration({ anchorBlockId: "gone" })],
      }),
    ).toEqual([]);
  });

  // 삽화 칸을 더하기 전의 API 로 되돌린 동안에는 응답에 칸이 없다 — 읽기 화면이 깨지지 않고 글만 보인다.
  it("reads a response without the illustrations field as no illustrations", () => {
    expect(toOwnerViewerIllustrations({ blocks: BLOCKS })).toEqual([]);
  });
});

describe("toPublicViewerIllustrations", () => {
  it("passes the reader response through as is", () => {
    const illustrations = [
      {
        paragraphIndex: 0,
        placement: "after" as const,
        order: 0,
        source: "original" as const,
        url: null,
        width: null,
        height: null,
        withheld: "original_restricted" as const,
        withheldReason: null,
      },
    ];
    expect(toPublicViewerIllustrations({ illustrations })).toEqual(illustrations);
  });

  it("reads a response without the illustrations field as no illustrations", () => {
    expect(toPublicViewerIllustrations({})).toEqual([]);
  });
});
