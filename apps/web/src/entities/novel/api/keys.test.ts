import { describe, expect, it } from "vitest";

import { novelKeys, novelScopedAll } from "./keys";

const NOVEL_ID = "novel-1";

function picks(queryKey: readonly unknown[]) {
  return novelScopedAll(NOVEL_ID)({ queryKey });
}

describe("novelScopedAll", () => {
  it("이 소설의 캐시는 종류와 상관없이 모두 고른다", () => {
    expect(picks(novelKeys.detail(NOVEL_ID))).toBe(true);
    expect(picks(novelKeys.job(NOVEL_ID, "job-1"))).toBe(true);
    expect(picks(novelKeys.chapter(NOVEL_ID, "chapter-1", "revision-1"))).toBe(true);
    expect(picks(novelKeys.revision(NOVEL_ID, "chapter-1", "revision-1"))).toBe(true);
    expect(picks(novelKeys.characters(NOVEL_ID))).toBe(true);
    expect(picks(novelKeys.episodeOutline(NOVEL_ID, "episode-1"))).toBe(true);
  });

  it("다른 소설의 캐시는 고르지 않는다", () => {
    expect(picks(novelKeys.detail("novel-2"))).toBe(false);
    expect(picks(novelKeys.chapter("novel-2", "chapter-1", "revision-1"))).toBe(false);
  });

  it("셋째 자리가 없는 목록·대화 소스 키는 고르지 않는다", () => {
    expect(picks(novelKeys.list())).toBe(false);
    expect(picks(novelKeys.sources())).toBe(false);
  });

  it("루트가 novel 이 아닌 키는 같은 소설 id 여도 고르지 않는다", () => {
    // 노벨(공개 소설) 캐시는 `["webnovel", 종류, novelId]` 꼴로 소설 id 를 같은 자리에 둔다.
    expect(picks(["webnovel", "detail", NOVEL_ID])).toBe(false);
    expect(picks(["webnovel", "chapter", NOVEL_ID, "chapter-1"])).toBe(false);
  });
});
