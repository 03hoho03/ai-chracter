import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { GENERIC_PERSONA_ERROR_MESSAGE, INVALID_PERSONA_INPUT_MESSAGE, personaErrorMessage } from "./personaErrorMessage";

describe("personaErrorMessage", () => {
  // 409는 서버가 보낸 한국어 문구를 그대로 쓴다(개수 사본을 두지 않는다).
  it("shows the server's Korean message for 409", () => {
    const error = new ApiErrorObject({
      status: 409,
      detail: "대화 프로필은 최대 10개까지 만들 수 있어요.",
      message: "대화 프로필은 최대 10개까지 만들 수 있어요.",
    });
    expect(personaErrorMessage(error)).toBe("대화 프로필은 최대 10개까지 만들 수 있어요.");
  });

  // 422 msg는 pydantic 원문(영문·"Value error," 접두사)이라 사용자에게 보이지 않는다.
  it("never shows the raw 422 message", () => {
    const error = new ApiErrorObject({
      status: 422,
      detail: undefined,
      message: "String should have at most 20 characters",
      fields: { name: "String should have at most 20 characters" },
    });
    expect(personaErrorMessage(error)).toBe(INVALID_PERSONA_INPUT_MESSAGE);
  });

  it("falls back to the generic copy for other statuses and non-API errors", () => {
    const error = new ApiErrorObject({ status: 404, detail: "Persona not found", message: "Persona not found" });
    expect(personaErrorMessage(error)).toBe(GENERIC_PERSONA_ERROR_MESSAGE);
    expect(personaErrorMessage(new Error("boom"))).toBe(GENERIC_PERSONA_ERROR_MESSAGE);
  });
});
