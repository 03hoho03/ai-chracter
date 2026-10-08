import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { addAlias, createCharacterMemoSchema, createCharacterNameSchema, toCharacterSaveError } from "./characterForm";

describe("addAlias", () => {
  it("adds a trimmed alias", () => {
    expect(addAlias(["희"], "도희", " 도희 씨 ", 5)).toEqual({ aliases: ["희", "도희 씨"] });
  });

  it("refuses an empty alias, the card's own name or an alias already there, and the count limit", () => {
    expect(addAlias([], "도희", "  ", 5)).toHaveProperty("error");
    expect(addAlias(["희"], "도희", "도희", 5)).toHaveProperty("error");
    expect(addAlias(["희"], "도희", "희", 5)).toHaveProperty("error");
    expect(addAlias(["희"], "도희", "희", 5)).toEqual({ error: "‘희’는 이미 이 인물의 이름이에요" });
    expect(addAlias(["a", "b"], "도희", "c", 2)).toEqual({ error: "별칭은 2개까지 둘 수 있어요" });
  });
});

describe("schemas", () => {
  it("name must be non-blank and within the limit; memo may be empty", () => {
    expect(createCharacterNameSchema(3).safeParse({ name: " " }).success).toBe(false);
    expect(createCharacterNameSchema(3).safeParse({ name: "도희야" }).success).toBe(true);
    expect(createCharacterNameSchema(3).safeParse({ name: "도희야아" }).success).toBe(false);
    expect(createCharacterMemoSchema(3).safeParse({ memo: "" }).success).toBe(true);
    expect(createCharacterMemoSchema(3).safeParse({ memo: "네 글자다" }).success).toBe(false);
  });
});

describe("toCharacterSaveError", () => {
  it("names the value another card already uses", () => {
    const error = new ApiErrorObject({
      status: 409,
      message: "x",
      detail: { code: "NOVEL_CHARACTER_NAME_TAKEN", name: "세빈" },
    });
    expect(toCharacterSaveError(error, "character")?.message).toBe(
      "‘세빈’은 다른 인물이 쓰고 있어요. 같은 인물이면 ‘다른 인물과 합치기’를 써주세요.",
    );
  });

  it("falls back to the shared novel sentence otherwise", () => {
    const error = new ApiErrorObject({ status: 404, message: "x", detail: { code: "NOVEL_CHARACTER_NOT_FOUND" } });
    expect(toCharacterSaveError(error, "character")).toEqual({
      message: "이 인물이 지워졌어요. 소설을 다시 불러왔어요.",
      shouldRefetchNovel: true,
    });
  });
});
