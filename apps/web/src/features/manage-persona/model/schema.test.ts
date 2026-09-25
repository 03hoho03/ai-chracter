import { describe, expect, it } from "vitest";

import { personaFormSchema } from "./schema";

function validValues() {
  return { name: "하늘", gender: "unspecified", description: "", setAsDefault: false };
}

describe("personaFormSchema", () => {
  // BE `persona/schemas.py`와 같은 규칙을 FE가 먼저 막는다(422 원문을
  // 사용자에게 보이지 않기 위해서다).
  it("accepts a 20-character name and a 500-character description", () => {
    const result = personaFormSchema.safeParse({
      ...validValues(),
      name: "가".repeat(20),
      description: "나".repeat(500),
    });
    expect(result.success).toBe(true);
  });

  it("trims the name before measuring and returns the trimmed value", () => {
    const result = personaFormSchema.safeParse({ ...validValues(), name: `  ${"가".repeat(20)}  ` });
    expect(result.success).toBe(true);
    expect(result.data?.name).toBe("가".repeat(20));
  });

  it.each([
    ["빈 이름", ""],
    ["공백만", "   "],
    ["21자", "가".repeat(21)],
    ["콜론", "a:b"],
    ["줄바꿈", "a\nb"],
    ["캐리지 리턴", "a\rb"],
  ])("rejects an invalid name (%s)", (_label, name) => {
    const result = personaFormSchema.safeParse({ ...validValues(), name });
    expect(result.success).toBe(false);
    expect(result.error?.issues.map((issue) => issue.path[0])).toEqual(["name"]);
  });

  it("allows a full-width colon because the stop sequence only sees the half-width one", () => {
    expect(personaFormSchema.safeParse({ ...validValues(), name: "a：b" }).success).toBe(true);
  });

  it("rejects a 501-character description but measures it after trimming", () => {
    expect(personaFormSchema.safeParse({ ...validValues(), description: "나".repeat(501) }).success).toBe(false);
    const trimmed = personaFormSchema.safeParse({ ...validValues(), description: ` ${"나".repeat(500)} ` });
    expect(trimmed.success).toBe(true);
    expect(trimmed.data?.description).toBe("나".repeat(500));
  });

  it("rejects a gender outside the three options", () => {
    expect(personaFormSchema.safeParse({ ...validValues(), gender: "other" }).success).toBe(false);
  });
});
