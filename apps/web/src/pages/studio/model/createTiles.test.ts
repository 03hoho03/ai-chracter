import { describe, expect, it } from "vitest";

import { toCreateTileKeys } from "./createTiles";

describe("toCreateTileKeys", () => {
  it("소설화가 열린 계정은 스토리와 이미지 생성 사이에 내 채팅으로 소설 칸을 받는다", () => {
    expect(toCreateTileKeys(true)).toEqual(["character", "story", "novel", "image"]);
  });

  it("소설화가 닫힌 계정은 소설 칸 없이 셋이다", () => {
    expect(toCreateTileKeys(false)).toEqual(["character", "story", "image"]);
  });
});
