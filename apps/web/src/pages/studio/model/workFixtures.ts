import type { ContentWorkItem, NovelWorkItem, NovelWorkPublication } from "@/entities/work";

/** 테스트 전용 작품 행. 문안은 합성이다. */
export function makeContentWork(overrides: Partial<ContentWorkItem> = {}): ContentWorkItem {
  return {
    kind: "character",
    id: "c-1",
    title: "비 오는 도서관",
    thumbnailUrl: null,
    editedAt: "2026-10-20T00:00:00Z",
    hasPublished: false,
    visibility: "private",
    moderationStatus: "normal",
    hasUnpublishedChanges: false,
    viewCount: 0,
    chatCount: 0,
    likeCount: 0,
    ...overrides,
  };
}

export function makePublication(overrides: Partial<NovelWorkPublication> = {}): NovelWorkPublication {
  return { visibility: "public", reviewStatus: "approved", moderationStatus: "normal", readable: true, ...overrides };
}

export function makeNovelWork(overrides: Partial<NovelWorkItem> = {}): NovelWorkItem {
  return {
    kind: "novel",
    id: "n-1",
    title: "새벽 편의점",
    contentTitle: "편의점 원작",
    characterName: null,
    cover: { assetId: null, url: null, source: "work" },
    chapterCount: 3,
    editedAt: "2026-10-20T00:00:00Z",
    publication: null,
    ...overrides,
  };
}
