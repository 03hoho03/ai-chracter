import { describe, expect, it } from "vitest";

import { countPersonaDescriptionChars, personaFormSchema } from "./schema";

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

  // 이름은 작가 글의 `{{user}}` 자리에 들어가 채팅 렌더러를 지난다 — 서버가 422 로 막는 이름을 폼이 먼저 막아야 서버의
  // 일반 오류 문구로 끝나지 않는다.
  it.each([
    ["별표", "*별*", "이름에는 별표(*)·백틱(`)·역슬래시(\\)나 &와 ;로 둘러싼 표기를 쓸 수 없어요"],
    ["문자 참조", "&#42;별", "이름에는 별표(*)·백틱(`)·역슬래시(\\)나 &와 ;로 둘러싼 표기를 쓸 수 없어요"],
    ["목록 표시로 시작", "- 별", "이름을 >, -, +, 1. 같은 인용·목록 표시나 ~~~ 로 시작하거나 ---·___ 로만 지을 수 없어요"],
    ["콜론", "a:b", "이름에는 콜론(:)이나 줄바꿈을 쓸 수 없어요"],
  ])("rejects a name the chat renderer would read as notation (%s) with the server's reason", (_label, name, message) => {
    const result = personaFormSchema.safeParse({ ...validValues(), name });
    expect(result.error?.issues.map((issue) => [issue.path[0], issue.message])).toEqual([["name", message]]);
  });

  it("checks the trimmed name, as the server does after stripping", () => {
    expect(personaFormSchema.safeParse({ ...validValues(), name: "  > 별" }).success).toBe(false);
    expect(personaFormSchema.safeParse({ ...validValues(), name: " 김-민 " }).success).toBe(true);
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

  // 서버는 앞뒤 공백을 뗀 뒤 코드 포인트로 한도를 잰다 — UTF-16 으로 재면 이모지 500자를 1000자로 보고 막는다.
  it("accepts 500 emoji and rejects 501, counting code points as the server does", () => {
    expect(personaFormSchema.safeParse({ ...validValues(), description: "😀".repeat(500) }).success).toBe(true);
    expect(personaFormSchema.safeParse({ ...validValues(), description: "😀".repeat(501) }).success).toBe(false);
  });

  it("rejects a gender outside the three options", () => {
    expect(personaFormSchema.safeParse({ ...validValues(), gender: "other" }).success).toBe(false);
  });
});

describe("countPersonaDescriptionChars", () => {
  it("counts an emoji as one character", () => {
    expect(countPersonaDescriptionChars("😀가")).toBe(2);
  });

  it("leaves out the surrounding whitespace the server strips", () => {
    expect(countPersonaDescriptionChars("  가 나\n ")).toBe(3);
  });
});
