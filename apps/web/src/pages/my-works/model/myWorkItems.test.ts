import { describe, expect, it } from "vitest";

import type { ContentSummary } from "@/entities/content";
import type { DraftSummary } from "@/entities/draft";

import { mergeMyWorks } from "./myWorkItems";

function makePublished(overrides: Partial<ContentSummary> & Pick<ContentSummary, "id" | "updatedAt">): ContentSummary {
  return {
    type: "character",
    name: "발행작",
    thumbnailAssetId: "asset-1",
    thumbnailUrl: null,
    viewCount: 0,
    chatCount: 0,
    likeCount: 0,
    visibility: "public",
    moderationStatus: "normal",
    ...overrides,
  };
}

function makeDraft(overrides: Partial<DraftSummary> & Pick<DraftSummary, "id" | "updatedAt">): DraftSummary {
  return {
    type: "story",
    name: "초안",
    thumbnailAssetId: null,
    thumbnailUrl: null,
    ...overrides,
  };
}

describe("mergeMyWorks", () => {
  it("발행작과 초안을 한 목록으로 합쳐 updatedAt 내림차순으로 세운다", () => {
    const merged = mergeMyWorks(
      [
        makePublished({ id: "c-old", updatedAt: "2026-08-01T00:00:00Z" }),
        makePublished({ id: "c-new", updatedAt: "2026-08-20T00:00:00Z" }),
      ],
      [makeDraft({ id: "d-mid", updatedAt: "2026-08-10T00:00:00Z" })],
    );

    expect(merged.map((item) => item.id)).toEqual(["c-new", "d-mid", "c-old"]);
  });

  it("발행작과 초안을 kind로 구분한다", () => {
    const merged = mergeMyWorks(
      [makePublished({ id: "c-1", updatedAt: "2026-08-20T00:00:00Z" })],
      [makeDraft({ id: "d-1", updatedAt: "2026-08-10T00:00:00Z" })],
    );

    expect(merged.map((item) => item.kind)).toEqual(["published", "draft"]);
  });

  it("updatedAt이 같으면 id 내림차순으로 끊는다 — 서버의 id DESC와 같은 규칙", () => {
    const sameMoment = "2026-08-20T00:00:00Z";
    const merged = mergeMyWorks(
      [
        makePublished({ id: "aaa", updatedAt: sameMoment }),
        makePublished({ id: "ccc", updatedAt: sameMoment }),
      ],
      [makeDraft({ id: "bbb", updatedAt: sameMoment })],
    );

    expect(merged.map((item) => item.id)).toEqual(["ccc", "bbb", "aaa"]);
  });

  it("한쪽이 비어 있어도 나머지를 그대로 돌려준다", () => {
    expect(mergeMyWorks([], [makeDraft({ id: "d-1", updatedAt: "2026-08-10T00:00:00Z" })])).toHaveLength(1);
    expect(mergeMyWorks([makePublished({ id: "c-1", updatedAt: "2026-08-10T00:00:00Z" })], [])).toHaveLength(1);
    expect(mergeMyWorks([], [])).toEqual([]);
  });
});
