import { describe, expect, it } from "vitest";

import { countInfoChars, createSynopsisFormSchema, createTitleFormSchema } from "./schema";

describe("countInfoChars", () => {
  it("앞뒤 공백을 걷고 코드 포인트로 센다", () => {
    expect(countInfoChars("  밤  ")).toBe(1);
    expect(countInfoChars("🌙밤")).toBe(2);
  });
});

describe("createTitleFormSchema", () => {
  const schema = createTitleFormSchema(5);

  it("빈 제목과 공백만 쓴 제목을 막는다", () => {
    expect(schema.safeParse({ title: "" }).success).toBe(false);
    expect(schema.safeParse({ title: "   " }).success).toBe(false);
  });

  it("상한까지는 받고 넘으면 막는다(앞뒤 공백은 세지 않는다)", () => {
    expect(schema.safeParse({ title: " 다섯글자다 " }).success).toBe(true);
    expect(schema.safeParse({ title: "여섯글자예요" }).success).toBe(false);
  });
});

describe("createSynopsisFormSchema", () => {
  const schema = createSynopsisFormSchema(3);

  it("빈 소개는 지우기라 받는다", () => {
    expect(schema.safeParse({ synopsis: "" }).success).toBe(true);
  });

  it("상한을 넘으면 막는다", () => {
    expect(schema.safeParse({ synopsis: "세글자" }).success).toBe(true);
    expect(schema.safeParse({ synopsis: "네글자다" }).success).toBe(false);
  });
});
