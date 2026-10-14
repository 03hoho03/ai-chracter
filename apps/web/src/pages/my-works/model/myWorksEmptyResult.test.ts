import { describe, expect, it } from "vitest";

import { resolveMyWorksEmptyResult, toMyWorksScopeLabel } from "./myWorksEmptyResult";

describe("resolveMyWorksEmptyResult", () => {
  it("검색도 칩 필터도 없으면 초안만 가진 상태다 — 조건 문장이 아니라 미등록 보기로 보낸다", () => {
    expect(resolveMyWorksEmptyResult({ q: undefined, filterLabel: undefined, hasMore: false })).toEqual({
      kind: "noPublished",
    });
  });

  it("검색만 걸렸으면 '찾은'이라고 말하고 검색어 지우기를 권한다", () => {
    expect(resolveMyWorksEmptyResult({ q: "목욕탕", filterLabel: undefined, hasMore: false })).toEqual({
      kind: "noMatch",
      message: "'목욕탕'으로 찾은 작품이 없어요.",
      action: "clearQuery",
    });
  });

  it("조사는 검색어 끝 글자에 맞춘다 — 받침 없음·ㄹ 받침은 '로', 한글이 아니면 두 꼴을 함께", () => {
    const messageOf = (q: string) => {
      const result = resolveMyWorksEmptyResult({ q, filterLabel: undefined, hasMore: false });
      return result.kind === "noMatch" ? result.message : undefined;
    };
    expect(messageOf("바다")).toBe("'바다'로 찾은 작품이 없어요.");
    expect(messageOf("마을")).toBe("'마을'로 찾은 작품이 없어요.");
    expect(messageOf("100%")).toBe("'100%'으로(로) 찾은 작품이 없어요.");
  });

  it("검색과 칩 필터가 함께 걸렸으면 둘을 한 문장에 적고 필터 모두 해제 하나로 둘 다 푼다", () => {
    expect(resolveMyWorksEmptyResult({ q: "목욕탕", filterLabel: "캐릭터 · 비공개", hasMore: false })).toEqual({
      kind: "noMatch",
      message: "'목욕탕' · 캐릭터 · 비공개에 해당하는 작품이 없어요.",
      action: "resetAll",
    });
  });

  it("칩 필터만 걸렸으면 예전 문장 그대로다", () => {
    expect(resolveMyWorksEmptyResult({ q: undefined, filterLabel: "비공개", hasMore: false })).toEqual({
      kind: "noMatch",
      message: "비공개에 해당하는 작품이 없어요.",
      action: "resetAll",
    });
  });

  it("남은 페이지가 있으면 문장의 범위를 불러온 만큼으로 좁힌다 — 공개범위는 화면이 걸러 다음 페이지에 있을 수 있다", () => {
    expect(resolveMyWorksEmptyResult({ q: undefined, filterLabel: "비공개", hasMore: true })).toEqual({
      kind: "noMatch",
      message: "지금까지 불러온 작품 중에는 비공개에 해당하는 게 없어요.",
      action: "resetAll",
    });
    expect(resolveMyWorksEmptyResult({ q: "목욕탕", filterLabel: "비공개", hasMore: true })).toEqual({
      kind: "noMatch",
      message: "지금까지 불러온 작품 중에는 '목욕탕' · 비공개에 해당하는 게 없어요.",
      action: "resetAll",
    });
  });
});

describe("toMyWorksScopeLabel", () => {
  it("아무것도 안 걸렸을 때만 '전체'다", () => {
    expect(toMyWorksScopeLabel({ q: undefined, filterLabel: undefined })).toBe("전체");
  });

  it("검색어와 칩 필터를 걸린 것만 이어 적는다", () => {
    expect(toMyWorksScopeLabel({ q: "목욕탕", filterLabel: undefined })).toBe("'목욕탕'");
    expect(toMyWorksScopeLabel({ q: undefined, filterLabel: "캐릭터" })).toBe("캐릭터");
    expect(toMyWorksScopeLabel({ q: "목욕탕", filterLabel: "캐릭터" })).toBe("'목욕탕' · 캐릭터");
  });
});
