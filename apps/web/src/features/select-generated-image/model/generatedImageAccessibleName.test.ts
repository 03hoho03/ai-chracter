import { describe, expect, it } from "vitest";

import { generatedImageAccessibleName } from "./generatedImageAccessibleName";

describe("generatedImageAccessibleName", () => {
  it("names a picture by its position and creation time so two pictures made in the same minute differ", () => {
    expect(generatedImageAccessibleName({ position: 1, createdAtLabel: "10월 2일 오후 3:24" })).toBe(
      "1번째 이미지, 10월 2일 오후 3:24 생성",
    );
    expect(generatedImageAccessibleName({ position: 2, createdAtLabel: "10월 2일 오후 3:24" })).toBe(
      "2번째 이미지, 10월 2일 오후 3:24 생성",
    );
  });

  it("says when the picture is the one already in the cell being filled", () => {
    expect(generatedImageAccessibleName({ position: 3, createdAtLabel: "10월 2일 오후 3:24", isCurrent: true })).toBe(
      "3번째 이미지, 10월 2일 오후 3:24 생성, 지금 이 칸의 이미지",
    );
  });

  it("names the other cells that already use the picture", () => {
    expect(
      generatedImageAccessibleName({
        position: 4,
        createdAtLabel: "10월 2일 오후 3:24",
        usedLabel: "도희 · 진심, 유나 · 리딩 칸에 씀",
      }),
    ).toBe("4번째 이미지, 10월 2일 오후 3:24 생성, 도희 · 진심, 유나 · 리딩 칸에 씀");
  });

  it("keeps both facts when the current picture is also used elsewhere", () => {
    expect(
      generatedImageAccessibleName({
        position: 5,
        createdAtLabel: "10월 2일 오후 3:24",
        isCurrent: true,
        usedLabel: "도희 · 진심 칸에 씀",
      }),
    ).toBe("5번째 이미지, 10월 2일 오후 3:24 생성, 지금 이 칸의 이미지, 도희 · 진심 칸에 씀");
  });
});
