import { describe, expect, it } from "vitest";

import { toStudioSearch } from "./legacyMyWorksSearch";
import { studioSearchSchema } from "./studioSearch";

describe("toStudioSearch", () => {
  it("캐릭터·스토리 유형은 같은 값으로 옮긴다", () => {
    expect(toStudioSearch({ type: "character" })).toEqual({ type: "character" });
    expect(toStudioSearch({ type: "story" })).toEqual({ type: "story" });
  });

  // 스튜디오에는 유형 `unpublished` 가 없다 — 그대로 흘리면 스튜디오 스키마가 모르는 값으로 보고 "전체"로 떨어뜨려
  // 초안만 보던 북마크가 소리 없이 모든 작품 목록이 된다.
  it("미등록 유형은 유형이 아니라 상태 초안으로 옮긴다", () => {
    expect(toStudioSearch({ type: "unpublished" })).toEqual({ status: "draft" });
  });

  it("미등록과 공개 범위가 함께 오면 초안이 이긴다 — 옛 화면도 미등록에서는 공개 범위를 무시했다", () => {
    expect(toStudioSearch({ type: "unpublished", visibility: "public" })).toEqual({ status: "draft" });
  });

  it("공개 범위 공개는 상태 공개 중으로 옮기고 유형은 지킨다", () => {
    expect(toStudioSearch({ visibility: "public" })).toEqual({ status: "public" });
    expect(toStudioSearch({ type: "story", visibility: "public" })).toEqual({ type: "story", status: "public" });
  });

  it("스튜디오에 대응하는 상태가 없는 링크 공개·비공개와 정렬은 버린다", () => {
    expect(toStudioSearch({ visibility: "link" })).toEqual({});
    expect(toStudioSearch({ visibility: "private" })).toEqual({});
    expect(toStudioSearch({ sort: "latest" })).toEqual({});
    expect(toStudioSearch({ type: "character", visibility: "private", sort: "latest" })).toEqual({ type: "character" });
  });

  it("검색어는 그대로 옮긴다", () => {
    expect(toStudioSearch({ q: "비 오는 밤" })).toEqual({ q: "비 오는 밤" });
    expect(toStudioSearch({ type: "unpublished", q: "초안" })).toEqual({ status: "draft", q: "초안" });
  });

  it("빈 조건은 빈 조건이고, 묶음은 어떤 입력에서도 싣지 않는다", () => {
    expect(toStudioSearch({})).toEqual({});
    expect(toStudioSearch({ type: "story", visibility: "public", q: "x" })).not.toHaveProperty("bundle");
  });

  // 리다이렉트가 넘긴 값을 스튜디오 라우트가 다시 읽는다 — 그 스키마가 값을 버리지 않아야 옮긴 필터가 살아남는다.
  it("옮긴 값은 스튜디오 서치 스키마를 거쳐도 그대로 남는다", () => {
    const moved = toStudioSearch({ type: "unpublished", q: "초안" });
    expect(studioSearchSchema.parse(moved)).toMatchObject({ status: "draft", q: "초안" });
  });
});
