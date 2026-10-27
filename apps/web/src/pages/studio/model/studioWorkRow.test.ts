import { describe, expect, it } from "vitest";

import { toStudioNextAction, toStudioStatusBadges, toStudioWorkTitle } from "./studioWorkRow";
import { makeContentWork, makeNovelWork, makePublication } from "./workFixtures";

describe("toStudioStatusBadges — 캐릭터·스토리", () => {
  it("발행한 적 없으면 초안 하나", () => {
    expect(toStudioStatusBadges(makeContentWork({ hasPublished: false }))).toEqual(["draft"]);
  });

  it("공개 범위가 공개인 발행작만 공개 중이고, 링크 공개·비공개는 발행됨이다", () => {
    expect(toStudioStatusBadges(makeContentWork({ hasPublished: true, visibility: "public" }))).toEqual(["public"]);
    expect(toStudioStatusBadges(makeContentWork({ hasPublished: true, visibility: "link" }))).toEqual(["published"]);
    expect(toStudioStatusBadges(makeContentWork({ hasPublished: true, visibility: "private" }))).toEqual([
      "published",
    ]);
  });

  it("수정본 있음은 공개 범위와 무관하게 붙는다", () => {
    expect(
      toStudioStatusBadges(makeContentWork({ hasPublished: true, visibility: "public", hasUnpublishedChanges: true })),
    ).toEqual(["public", "changed"]);
    expect(
      toStudioStatusBadges(makeContentWork({ hasPublished: true, visibility: "private", hasUnpublishedChanges: true })),
    ).toEqual(["published", "changed"]);
  });

  it("이용제한 작품은 공개 범위가 공개여도 공개 중이 아니라 발행됨 + 이용제한이다", () => {
    expect(
      toStudioStatusBadges(makeContentWork({ hasPublished: true, visibility: "public", moderationStatus: "restricted" })),
    ).toEqual(["published", "restricted"]);
  });
});

describe("toStudioStatusBadges — 소설", () => {
  it("공개하지 않은 소설은 배지가 없다", () => {
    expect(toStudioStatusBadges(makeNovelWork({ publication: null }))).toEqual([]);
  });

  it("공개 중은 독자가 읽을 수 있을 때만이고, 승인된 공개라도 읽을 수 없으면 독자에게 안 보임이다", () => {
    expect(toStudioStatusBadges(makeNovelWork({ publication: makePublication({ readable: true }) }))).toEqual([
      "public",
    ]);
    expect(toStudioStatusBadges(makeNovelWork({ publication: makePublication({ readable: false }) }))).toEqual([
      "hiddenFromReaders",
    ]);
  });

  it("거둔 공개는 공개 거둠", () => {
    expect(
      toStudioStatusBadges(
        makeNovelWork({ publication: makePublication({ visibility: "withdrawn", readable: false }) }),
      ),
    ).toEqual(["withdrawn"]);
  });

  it("첫 공개 대기는 심사 대기, 반려는 반려다(공개 범위가 거둠이어도)", () => {
    expect(
      toStudioStatusBadges(
        makeNovelWork({
          publication: makePublication({ visibility: "withdrawn", reviewStatus: "pending", readable: false }),
        }),
      ),
    ).toEqual(["inReview"]);
    expect(
      toStudioStatusBadges(
        makeNovelWork({
          publication: makePublication({ visibility: "withdrawn", reviewStatus: "rejected", readable: false }),
        }),
      ),
    ).toEqual(["rejected"]);
  });

  it("운영 이용제한은 대기·공개보다 앞선다", () => {
    expect(
      toStudioStatusBadges(
        makeNovelWork({
          publication: makePublication({ moderationStatus: "restricted", reviewStatus: "pending", readable: false }),
        }),
      ),
    ).toEqual(["restricted"]);
  });
});

describe("toStudioNextAction", () => {
  it("초안은 이어 쓰기로 빌더에 간다", () => {
    expect(toStudioNextAction(makeContentWork({ kind: "story", id: "s-9" }))).toEqual({
      label: "이어 쓰기",
      target: { kind: "builder", type: "story", id: "s-9" },
    });
  });

  it("수정본 있는 발행작은 공개 준비, 없는 발행작은 수정하기", () => {
    expect(toStudioNextAction(makeContentWork({ hasPublished: true, hasUnpublishedChanges: true })).label).toBe(
      "공개 준비",
    );
    expect(toStudioNextAction(makeContentWork({ hasPublished: true, hasUnpublishedChanges: false })).label).toBe(
      "수정하기",
    );
  });

  it("이용제한 작품은 수정본이 있어도 수정하기다", () => {
    expect(
      toStudioNextAction(
        makeContentWork({ hasPublished: true, hasUnpublishedChanges: true, moderationStatus: "restricted" }),
      ).label,
    ).toBe("수정하기");
  });

  it("소설은 작품 정보로 간다", () => {
    expect(toStudioNextAction(makeNovelWork({ id: "n-7" }))).toEqual({
      label: "소설 열기",
      target: { kind: "novel", id: "n-7" },
    });
  });
});

describe("toStudioWorkTitle", () => {
  it("이름 없는 초안은 자리 문구를, 이름이 있으면 그 이름을 쓴다", () => {
    expect(toStudioWorkTitle(makeContentWork({ title: "" }))).toBe("제목 없는 초안");
    expect(toStudioWorkTitle(makeContentWork({ title: "옥상 정원" }))).toBe("옥상 정원");
  });

  it("소설은 소설 제목, 없으면 원작 제목", () => {
    expect(toStudioWorkTitle(makeNovelWork({ title: "겨울 방학", contentTitle: "원작" }))).toBe("겨울 방학");
    expect(toStudioWorkTitle(makeNovelWork({ title: null, contentTitle: "원작" }))).toBe("원작");
  });
});
