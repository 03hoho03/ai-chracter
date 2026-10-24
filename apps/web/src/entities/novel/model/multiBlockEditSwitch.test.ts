import { describe, expect, it } from "vitest";

import { isNovelMultiBlockEditOn } from "./multiBlockEditSwitch";

/** 앱 소스 전부(시험 파일 제외 — 시험은 칸 이름을 써서 판정을 부른다). */
const SOURCES = import.meta.glob<string>(["../../../**/*.ts", "../../../**/*.tsx", "!../../../**/*.test.ts"], {
  query: "?raw",
  import: "default",
  eager: true,
});

describe("isNovelMultiBlockEditOn", () => {
  it.each([undefined, {}, { novelizeMultiBlockEditEnabled: false }])(
    "꺼짐·가격을 못 받음·칸 없는 응답은 거짓이다 (%o)",
    (pricing) => {
      expect(isNovelMultiBlockEditOn(pricing)).toBe(false);
    },
  );

  it("켜짐이면 참이다", () => {
    expect(isNovelMultiBlockEditOn({ novelizeMultiBlockEditEnabled: true })).toBe(true);
  });

  // 다른 곳이 칸을 직접 읽으면 꺼짐·로딩·실패를 다르게 접는 화면이 생겨, 스위치를 꺼도 여러 문단 고르기가 남는 길이 열린다.
  it("스위치 칸을 읽는 소스는 판정 함수 파일 하나뿐이다", () => {
    const readers = Object.entries(SOURCES)
      .filter(([, source]) => source.includes("novelizeMultiBlockEditEnabled"))
      .map(([path]) => path);
    expect(readers).toEqual(["./multiBlockEditSwitch.ts"]);
    expect(Object.keys(SOURCES)).toContain("../../../features/edit-novel-chapter/ui/NovelChapterText.tsx");
  });
});
