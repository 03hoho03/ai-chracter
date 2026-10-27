import { describe, expect, it } from "vitest";

import { isDerivedNovelsRequestable, toDerivedNovelsArea } from "./derivedNovelsArea";

const ITEM = { id: "novel-1" };

describe("isDerivedNovelsRequestable", () => {
  it("비로그인이면 노벨이 모두에게 열려 있어도 부르지 않는다", () => {
    expect(isDerivedNovelsRequestable({ isLoggedIn: false, pricingEnabled: true, sessionEnabled: undefined })).toBe(false);
  });

  it("로그인했어도 노벨이 닫혀 있으면 부르지 않는다", () => {
    expect(isDerivedNovelsRequestable({ isLoggedIn: true, pricingEnabled: false, sessionEnabled: false })).toBe(false);
  });

  it("로그인했고 노벨이 모두에게 열려 있으면 부른다", () => {
    expect(isDerivedNovelsRequestable({ isLoggedIn: true, pricingEnabled: true, sessionEnabled: false })).toBe(true);
  });

  it("로그인했고 미리보기 명단으로만 열려 있어도 부른다", () => {
    expect(isDerivedNovelsRequestable({ isLoggedIn: true, pricingEnabled: false, sessionEnabled: true })).toBe(true);
  });
});

describe("toDerivedNovelsArea", () => {
  it("항목이 하나도 없으면 영역을 그리지 않는다", () => {
    expect(
      toDerivedNovelsArea({ pages: [{ items: [] }], isOwner: true, derivedNovelsVisible: false }),
    ).toEqual({ kind: "none" });
  });

  it("응답이 아직 없으면 영역을 그리지 않는다", () => {
    expect(toDerivedNovelsArea({ pages: undefined, isOwner: false, derivedNovelsVisible: true })).toEqual({
      kind: "none",
    });
  });

  it("여러 페이지의 항목을 이어 붙인다", () => {
    const area = toDerivedNovelsArea({
      pages: [{ items: [ITEM] }, { items: [{ id: "novel-2" }] }],
      isOwner: false,
      derivedNovelsVisible: true,
    });
    expect(area).toEqual({ kind: "list", items: [ITEM, { id: "novel-2" }], isHiddenFromOthers: false });
  });

  it("원작자가 숨겨 두었으면 원작자 본인에게 숨김 중이라고 알린다", () => {
    const area = toDerivedNovelsArea({ pages: [{ items: [ITEM] }], isOwner: true, derivedNovelsVisible: false });
    expect(area).toEqual({ kind: "list", items: [ITEM], isHiddenFromOthers: true });
  });

  it("숨기지 않았으면 원작자 본인에게도 숨김 줄이 없다", () => {
    const area = toDerivedNovelsArea({ pages: [{ items: [ITEM] }], isOwner: true, derivedNovelsVisible: true });
    expect(area).toEqual({ kind: "list", items: [ITEM], isHiddenFromOthers: false });
  });

  it("원작자가 아닌 사람에게는 숨김 줄을 내지 않는다", () => {
    const area = toDerivedNovelsArea({ pages: [{ items: [ITEM] }], isOwner: false, derivedNovelsVisible: false });
    expect(area).toEqual({ kind: "list", items: [ITEM], isHiddenFromOthers: false });
  });

  it("숨김 여부는 목록 응답이 아니라 작품 상세 값을 따른다 — 목록 응답이 토글 전 값이어도", () => {
    // 목록 응답은 숨김을 켜기 전에 받아 둔 것(visible 참)이고, 작품 상세는 토글 뒤 다시 받은 값(거짓)이다.
    const turnedOff = toDerivedNovelsArea({
      pages: [{ visible: true, items: [ITEM] }],
      isOwner: true,
      derivedNovelsVisible: false,
    });
    expect(turnedOff).toEqual({ kind: "list", items: [ITEM], isHiddenFromOthers: true });

    const turnedOn = toDerivedNovelsArea({
      pages: [{ visible: false, items: [ITEM] }],
      isOwner: true,
      derivedNovelsVisible: true,
    });
    expect(turnedOn).toEqual({ kind: "list", items: [ITEM], isHiddenFromOthers: false });
  });
});
