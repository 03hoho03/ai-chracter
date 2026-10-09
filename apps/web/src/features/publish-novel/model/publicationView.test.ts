import { describe, expect, it } from "vitest";

import type { NovelPublicationStatus } from "@/entities/novel";

import {
  toPublicationView,
  toPublicPendingLines,
  toPublishRange,
  toPublishRequests,
  toRejectionNotice,
} from "./publicationView";

function status(patch: Partial<NovelPublicationStatus>): NovelPublicationStatus {
  return {
    published: false,
    visibility: null,
    moderationStatus: null,
    publishedChapterCount: 0,
    chapterCount: 8,
    changedChapterOrdinals: [],
    metadataChanged: false,
    newPublishBlock: null,
    republishBlock: null,
    lastScreening: null,
    screeningRejectionsLeft: 3,
    screeningRejectionLimit: 3,
    firstPublishedAt: null,
    publishedAt: null,
    ...patch,
  };
}

const PUBLIC = { published: true, visibility: "public", moderationStatus: "normal" } as const;
const chapters = Array.from({ length: 8 }, (_, index) => ({ id: `c${index + 1}`, ordinal: index + 1 }));

describe("toPublicationView", () => {
  it("공개한 적 없는 소설은 원작 판정에 따라 공개 가능·막힘으로 갈린다", () => {
    expect(toPublicationView(status({}))).toEqual({ kind: "unpublished" });
    expect(toPublicationView(status({ newPublishBlock: "source_permission" }))).toEqual({ kind: "blocked", block: "permission" });
    expect(toPublicationView(status({ newPublishBlock: "source_not_listed" }))).toEqual({ kind: "blocked", block: "source" });
    expect(toPublicationView(status({ chapterCount: 0 }))).toEqual({ kind: "noChapters" });
  });

  it("운영 조치는 거둠·공개 중보다 앞선다", () => {
    expect(toPublicationView(status({ ...PUBLIC, moderationStatus: "restricted", visibility: "withdrawn" }))).toEqual({
      kind: "restricted",
    });
  });

  it("거둔 공개는 원작이 공개돼 있어야 다시 열 수 있다", () => {
    expect(toPublicationView(status({ ...PUBLIC, visibility: "withdrawn" }))).toEqual({ kind: "withdrawn", canReopen: true });
    expect(
      toPublicationView(status({ ...PUBLIC, visibility: "withdrawn", republishBlock: "source_unavailable" })),
    ).toEqual({ kind: "withdrawn", canReopen: false });
  });

  it("공개 중이면 새 화나 고친 내용이 있을 때만 다시 공개할 것이 있다", () => {
    const allPublished = toPublicationView(status({ ...PUBLIC, publishedChapterCount: 8 }));
    expect(allPublished).toMatchObject({ kind: "public", unpublishedCount: 0, canRepublish: false });
    expect(toPublicationView(status({ ...PUBLIC, publishedChapterCount: 6 }))).toMatchObject({ canRepublish: true });
    expect(
      toPublicationView(status({ ...PUBLIC, publishedChapterCount: 8, changedChapterOrdinals: [5, 3] })),
    ).toMatchObject({ canRepublish: true, changedOrdinals: [3, 5] });
  });

  it("허락이 낮아지면 새 화는 못 내도 고친 화는 다시 낼 수 있다", () => {
    const view = toPublicationView(
      status({ ...PUBLIC, publishedChapterCount: 6, newPublishBlock: "source_permission" }),
    );
    expect(view).toMatchObject({ newBlock: "permission", canRepublish: false });
    expect(
      toPublicationView(
        status({ ...PUBLIC, publishedChapterCount: 6, newPublishBlock: "source_permission", changedChapterOrdinals: [2] }),
      ),
    ).toMatchObject({ canRepublish: true });
  });
});

describe("toPublishRange", () => {
  it("처음 공개는 1화부터 마지막 화까지 고를 수 있다", () => {
    expect(toPublishRange(status({}))).toEqual({ min: 1, max: 8 });
  });

  it("다시 공개는 지금 공개 범위보다 줄일 수 없고, 새 화를 못 내면 지금 범위에 묶인다", () => {
    expect(toPublishRange(status({ ...PUBLIC, publishedChapterCount: 5 }))).toEqual({ min: 5, max: 8 });
    expect(toPublishRange(status({ ...PUBLIC, publishedChapterCount: 5, newPublishBlock: "source_permission" }))).toEqual({
      min: 5,
      max: 5,
    });
  });

  it("공개한 적 없이 막혔거나 화가 없으면 고를 것이 없다", () => {
    expect(toPublishRange(status({ newPublishBlock: "source_permission" }))).toBeUndefined();
    expect(toPublishRange(status({ chapterCount: 0 }))).toBeUndefined();
  });
});

describe("toPublishRequests", () => {
  it("1화부터 고른 화까지 한 화씩 차례로 보낸다", () => {
    expect(toPublishRequests({ status: status({}), chapters, targetOrdinal: 3 })).toEqual(["c1", "c2", "c3"]);
  });

  it("고친 화를 먼저 다시 내고 그다음 새 화를 잇는다", () => {
    expect(
      toPublishRequests({
        status: status({ ...PUBLIC, publishedChapterCount: 5, changedChapterOrdinals: [4, 2] }),
        chapters,
        targetOrdinal: 7,
      }),
    ).toEqual(["c2", "c4", "c6", "c7"]);
  });

  it("화를 다시 낼 것이 없어도 제목·소개가 바뀌었거나 거둔 공개면 화 없이 한 번 보낸다", () => {
    const published = { ...PUBLIC, publishedChapterCount: 8 };
    expect(toPublishRequests({ status: status({ ...published, metadataChanged: true }), chapters, targetOrdinal: 8 })).toEqual([
      null,
    ]);
    expect(
      toPublishRequests({ status: status({ ...published, visibility: "withdrawn" }), chapters, targetOrdinal: 8 }),
    ).toEqual([null]);
    expect(toPublishRequests({ status: status(published), chapters, targetOrdinal: 8 })).toEqual([]);
  });
});

describe("toPublicPendingLines", () => {
  it("공개하지 않은 화와 공개한 뒤 고친 화·제목·소개를 말한다", () => {
    const view = toPublicationView(
      status({ ...PUBLIC, publishedChapterCount: 8, chapterCount: 10, changedChapterOrdinals: [3, 5], metadataChanged: true }),
    );
    if (view.kind !== "public") throw new Error("공개 중이어야 한다");
    expect(toPublicPendingLines(view, { republishBlocked: false })).toEqual([
      "9~10화는 아직 공개하지 않았어요.",
      "공개한 뒤 고친 화 2개(3화·5화)와 제목·소개가 노벨에는 아직 옛 내용이에요.",
    ]);
  });

  it("남은 것이 없으면 아무것도 말하지 않는다", () => {
    const view = toPublicationView(status({ ...PUBLIC, publishedChapterCount: 8 }));
    if (view.kind !== "public") throw new Error("공개 중이어야 한다");
    expect(toPublicPendingLines(view, { republishBlocked: false })).toEqual([]);
  });
});

describe("toRejectionNotice", () => {
  it("걸린 화의 글과 고치러 갈 화를 말한다", () => {
    expect(toRejectionNotice({ chapterOrdinal: 6, flaggedParts: ["chapter_body"] })).toEqual({
      message: "6화의 본문이 운영 정책에 맞지 않는 내용으로 확인돼 공개하지 못했어요. 6화를 고친 뒤 다시 공개해 주세요.",
      fixOrdinal: 6,
    });
  });

  it("제목·소개만 걸리면 고칠 화가 없다", () => {
    expect(toRejectionNotice({ chapterOrdinal: null, flaggedParts: ["synopsis"] })).toEqual({
      message: "소개가 운영 정책에 맞지 않는 내용으로 확인돼 공개하지 못했어요. 소개를 고친 뒤 다시 공개해 주세요.",
      fixOrdinal: undefined,
    });
  });
});
