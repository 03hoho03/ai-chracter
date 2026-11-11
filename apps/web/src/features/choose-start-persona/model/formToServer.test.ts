import { describe, expect, it } from "vitest";

import { FIRST_PERSONA_NAME_SCHEMA } from "./firstPersonaNameSchema";
import { formToServer } from "./formToServer";

// 화면 제출과 같은 경로(스키마 파싱 → 본문 변환)로 확인한다 — 스키마는 검사만, 공백 걷기는 변환이 한다.
function toBody(raw: unknown) {
  return formToServer(FIRST_PERSONA_NAME_SCHEMA.parse(raw));
}

describe("first persona name body", () => {
  it("sends the trimmed name as a new default profile with no gender or description", () => {
    expect(toBody({ name: "  하늘  " })).toEqual({ name: "하늘", gender: null, description: "", setAsDefault: true });
  });

  it("rejects an empty or whitespace-only name before it reaches the body", () => {
    expect(FIRST_PERSONA_NAME_SCHEMA.safeParse({ name: "" }).success).toBe(false);
    expect(FIRST_PERSONA_NAME_SCHEMA.safeParse({ name: "   " }).success).toBe(false);
  });
});
