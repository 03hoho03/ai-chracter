import { describe, expect, it } from "vitest";

import { resolveMyWorksEmptyResult, toMyWorksScopeLabel } from "./myWorksEmptyResult";

describe("resolveMyWorksEmptyResult", () => {
  it("검색도 칩 필터도 없으면 초안만 가진 상태다 — 조건 문장이 아니라 미등록 보기로 보낸다", () => {
    expect(resolveMyWorksEmptyResult({ q: undefined, filterLabel: undefined, hasUnpublishedMatch: true, hasMore: false })).toEqual({
      kind: "noPublished",
      message: "아직 발행한 작품이 없어요.",
    });
  });

  it("검색만 걸렸으면 '찾은'이라고 말하고 검색어 지우기를 권한다", () => {
    expect(resolveMyWorksEmptyResult({ q: "목욕탕", filterLabel: undefined, hasUnpublishedMatch: false, hasMore: false })).toEqual({
      kind: "noMatch",
      message: "‘목욕탕’으로 찾은 작품이 없어요.",
      action: "clearQuery",
    });
  });

  it("조사는 검색어 끝 글자에 맞춘다 — 받침 없음·ㄹ 받침은 '로', 한글이 아니면 '(으)로'", () => {
    const messageOf = (q: string) => {
      const result = resolveMyWorksEmptyResult({ q, filterLabel: undefined, hasUnpublishedMatch: false, hasMore: false });
      return result.kind === "noMatch" ? result.message : undefined;
    };
    expect(messageOf("바다")).toBe("‘바다’로 찾은 작품이 없어요.");
    expect(messageOf("마을")).toBe("‘마을’로 찾은 작품이 없어요.");
    expect(messageOf("100%")).toBe("‘100%’(으)로 찾은 작품이 없어요.");
    expect(messageOf("zq")).toBe("‘zq’(으)로 찾은 작품이 없어요.");
  });

  it("미등록 안내도 한글이 아닌 끝 글자 뒤에는 '(으)로'다", () => {
    expect(resolveMyWorksEmptyResult({ q: "zq", filterLabel: undefined, hasUnpublishedMatch: true, hasMore: false })).toEqual({
      kind: "noPublished",
      message: "‘zq’(으)로 찾은 작품은 미등록에 있어요.",
    });
  });

  it("검색과 칩 필터가 함께 걸렸으면 둘을 한 문장에 적고 필터 모두 해제 하나로 둘 다 푼다", () => {
    expect(resolveMyWorksEmptyResult({ q: "목욕탕", filterLabel: "캐릭터 · 비공개", hasUnpublishedMatch: false, hasMore: false })).toEqual({
      kind: "noMatch",
      message: "‘목욕탕’ · 캐릭터 · 비공개에 해당하는 작품이 없어요.",
      action: "resetAll",
    });
  });

  it("칩 필터 없이 검색했는데 걸린 게 초안뿐이면 찾은 작품이 미등록에 있다고 말하고 미등록 보기를 권한다", () => {
    expect(resolveMyWorksEmptyResult({ q: "고래", filterLabel: undefined, hasUnpublishedMatch: true, hasMore: false })).toEqual({
      kind: "noPublished",
      message: "‘고래’로 찾은 작품은 미등록에 있어요.",
    });
    expect(resolveMyWorksEmptyResult({ q: "목욕탕", filterLabel: undefined, hasUnpublishedMatch: true, hasMore: false })).toEqual({
      kind: "noPublished",
      message: "‘목욕탕’으로 찾은 작품은 미등록에 있어요.",
    });
  });

  it("칩 필터가 걸렸으면 초안에 걸린 게 있어도 조건 문장이다 — 미등록 칩에서는 초안도 0건이고, 다른 칩은 고른 축을 말해야 한다", () => {
    expect(resolveMyWorksEmptyResult({ q: "고래", filterLabel: "캐릭터", hasUnpublishedMatch: true, hasMore: false })).toEqual({
      kind: "noMatch",
      message: "‘고래’ · 캐릭터에 해당하는 작품이 없어요.",
      action: "resetAll",
    });
  });

  it("칩 필터만 걸렸으면 예전 문장 그대로다", () => {
    expect(resolveMyWorksEmptyResult({ q: undefined, filterLabel: "비공개", hasUnpublishedMatch: false, hasMore: false })).toEqual({
      kind: "noMatch",
      message: "비공개에 해당하는 작품이 없어요.",
      action: "resetAll",
    });
  });

  it("남은 페이지가 있으면 문장의 범위를 불러온 만큼으로 좁힌다 — 공개범위는 화면이 걸러 다음 페이지에 있을 수 있다", () => {
    expect(resolveMyWorksEmptyResult({ q: undefined, filterLabel: "비공개", hasUnpublishedMatch: false, hasMore: true })).toEqual({
      kind: "noMatch",
      message: "지금까지 불러온 작품 중에는 비공개에 해당하는 게 없어요.",
      action: "resetAll",
    });
    expect(resolveMyWorksEmptyResult({ q: "목욕탕", filterLabel: "비공개", hasUnpublishedMatch: false, hasMore: true })).toEqual({
      kind: "noMatch",
      message: "지금까지 불러온 작품 중에는 ‘목욕탕’ · 비공개에 해당하는 게 없어요.",
      action: "resetAll",
    });
  });
});

describe("toMyWorksScopeLabel", () => {
  it("아무것도 안 걸렸을 때만 '전체'다", () => {
    expect(toMyWorksScopeLabel({ q: undefined, filterLabel: undefined })).toBe("전체");
  });

  it("검색어와 칩 필터를 걸린 것만 이어 적는다", () => {
    expect(toMyWorksScopeLabel({ q: "목욕탕", filterLabel: undefined })).toBe("‘목욕탕’");
    expect(toMyWorksScopeLabel({ q: undefined, filterLabel: "캐릭터" })).toBe("캐릭터");
    expect(toMyWorksScopeLabel({ q: "목욕탕", filterLabel: "캐릭터" })).toBe("‘목욕탕’ · 캐릭터");
  });
});
