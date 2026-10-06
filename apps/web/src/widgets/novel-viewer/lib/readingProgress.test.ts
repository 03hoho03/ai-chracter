import { describe, expect, it } from "vitest";

import { toEpisodeScrollProgress, toNovelReadProgress } from "./readingProgress";

describe("toEpisodeScrollProgress", () => {
  it("스크롤 위치를 스크롤할 수 있는 거리로 나눈다", () => {
    expect(toEpisodeScrollProgress({ scrollTop: 0, scrollHeight: 3000, clientHeight: 1000 })).toBe(0);
    expect(toEpisodeScrollProgress({ scrollTop: 500, scrollHeight: 3000, clientHeight: 1000 })).toBe(0.25);
    expect(toEpisodeScrollProgress({ scrollTop: 2000, scrollHeight: 3000, clientHeight: 1000 })).toBe(1);
  });

  it("고무줄 스크롤로 범위를 벗어난 값은 0 … 1 로 자른다", () => {
    expect(toEpisodeScrollProgress({ scrollTop: -40, scrollHeight: 3000, clientHeight: 1000 })).toBe(0);
    expect(toEpisodeScrollProgress({ scrollTop: 2100, scrollHeight: 3000, clientHeight: 1000 })).toBe(1);
  });

  it("본문이 화면 안에 다 들어오면 1", () => {
    expect(toEpisodeScrollProgress({ scrollTop: 0, scrollHeight: 800, clientHeight: 1000 })).toBe(1);
    expect(toEpisodeScrollProgress({ scrollTop: 0, scrollHeight: 1000, clientHeight: 1000 })).toBe(1);
  });
});

describe("toNovelReadProgress", () => {
  it("다 읽은 화 수를 전체 화 수로 나눈다", () => {
    expect(toNovelReadProgress(0, 4)).toBe(0);
    expect(toNovelReadProgress(1, 4)).toBe(0.25);
    expect(toNovelReadProgress(4, 4)).toBe(1);
  });

  it("화가 없으면 0, 넘치는 값은 1 로 자른다", () => {
    expect(toNovelReadProgress(0, 0)).toBe(0);
    expect(toNovelReadProgress(5, 4)).toBe(1);
  });
});
