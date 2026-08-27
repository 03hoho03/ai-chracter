import { describe, expect, it } from "vitest";

import type { ContentSummary } from "@/entities/content";
import type { DraftSummary } from "@/entities/draft";

import { filterMyWorks, mergeMyWorks, toMyWorkTags } from "./myWorkItems";

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
    hasUnpublishedChanges: false,
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

describe("filterMyWorks", () => {
  const published = [
    makePublished({ id: "c-public", type: "character", visibility: "public", updatedAt: "2026-08-20T00:00:00Z" }),
    makePublished({ id: "c-private", type: "character", visibility: "private", updatedAt: "2026-08-19T00:00:00Z" }),
    makePublished({ id: "s-link", type: "story", visibility: "link", updatedAt: "2026-08-18T00:00:00Z" }),
  ];
  const drafts = [
    makeDraft({ id: "d-1", type: "character", updatedAt: "2026-08-21T00:00:00Z" }),
    makeDraft({ id: "d-2", type: "story", updatedAt: "2026-08-17T00:00:00Z" }),
  ];
  const items = mergeMyWorks(published, drafts);

  it("전체에는 초안이 섞이지 않는다 — FR-18", () => {
    const filtered = filterMyWorks(items, { type: "all", visibility: "all" });

    expect(filtered.map((item) => item.id)).toEqual(["c-public", "c-private", "s-link"]);
  });

  it("미등록은 초안만 돌려준다 — 발행작이 섞이지 않는다", () => {
    const filtered = filterMyWorks(items, { type: "unpublished", visibility: "all" });

    expect(filtered.map((item) => item.id)).toEqual(["d-1", "d-2"]);
  });

  it("캐릭터·스토리는 그 유형의 발행작만 돌려준다", () => {
    expect(filterMyWorks(items, { type: "character", visibility: "all" }).map((item) => item.id)).toEqual([
      "c-public",
      "c-private",
    ]);
    expect(filterMyWorks(items, { type: "story", visibility: "all" }).map((item) => item.id)).toEqual(["s-link"]);
  });

  it("공개 여부는 발행작을 한 겹 더 좁힌다", () => {
    expect(filterMyWorks(items, { type: "all", visibility: "private" }).map((item) => item.id)).toEqual(["c-private"]);
    expect(filterMyWorks(items, { type: "all", visibility: "link" }).map((item) => item.id)).toEqual(["s-link"]);
    expect(filterMyWorks(items, { type: "character", visibility: "public" }).map((item) => item.id)).toEqual([
      "c-public",
    ]);
  });

  it("미등록에서는 공개 여부를 보지 않는다 — 손으로 만든 URL도 무해해야 한다", () => {
    const filtered = filterMyWorks(items, { type: "unpublished", visibility: "public" });

    expect(filtered.map((item) => item.id)).toEqual(["d-1", "d-2"]);
  });

  // 화면의 "아직 발행한 작품이 없어요 / 미등록 보기" 분기가 이 불변식 위에 서 있다 — 필터가 안 걸렸는데
  // 0건이면 남은 건 초안뿐이므로 `미등록 보기`는 반드시 1건 이상으로 간다(죽은 버튼이 될 수 없다).
  it("필터 없이 0건이면 목록은 전부 초안이다 — 미등록이 그 항목들을 그대로 돌려준다", () => {
    const draftsOnly = mergeMyWorks([], drafts);

    expect(filterMyWorks(draftsOnly, { type: "all", visibility: "all" })).toEqual([]);
    expect(filterMyWorks(draftsOnly, { type: "unpublished", visibility: "all" })).toHaveLength(drafts.length);
  });

  it("병합 정렬 순서를 그대로 보존한다", () => {
    const filtered = filterMyWorks(items, { type: "all", visibility: "all" });

    expect(filtered.map((item) => item.updatedAt)).toEqual([
      "2026-08-20T00:00:00Z",
      "2026-08-19T00:00:00Z",
      "2026-08-18T00:00:00Z",
    ]);
  });
});

describe("toMyWorkTags", () => {
  it("이용제한 발행작에 이용제한 배지를 단다 — 공개범위 배지와 함께", () => {
    const restricted = makePublished({
      id: "c-1",
      updatedAt: "2026-08-20T00:00:00Z",
      visibility: "public",
      moderationStatus: "restricted",
    });

    expect(toMyWorkTags({ kind: "published", ...restricted })).toEqual(["character", "public", "restricted"]);
  });

  it("이용제한이 아닌 발행작에는 타입과 공개범위 둘만 단다", () => {
    const normal = makePublished({
      id: "c-2",
      updatedAt: "2026-08-20T00:00:00Z",
      visibility: "private",
    });

    expect(toMyWorkTags({ kind: "published", ...normal })).toEqual(["character", "private"]);
  });

  it("초안은 공개범위가 없어 미등록 하나만 단다", () => {
    const draft = makeDraft({ id: "d-1", updatedAt: "2026-08-20T00:00:00Z" });

    expect(toMyWorkTags({ kind: "draft", ...draft })).toEqual(["story", "unpublished"]);
  });
});
