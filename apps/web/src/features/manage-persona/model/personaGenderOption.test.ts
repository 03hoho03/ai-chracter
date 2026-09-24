import { describe, expect, it } from "vitest";

import { PERSONA_GENDER_OPTION_LABEL, toPersonaGenderOption } from "./personaGenderOption";

describe("personaGenderOption", () => {
  it("labels the three choices, 'unspecified' as 선택 안 함", () => {
    expect(PERSONA_GENDER_OPTION_LABEL).toEqual({ unspecified: "선택 안 함", male: "남성", female: "여성" });
  });

  it("folds the empty re-click value and unknown values to undefined", () => {
    expect(toPersonaGenderOption("")).toBeUndefined();
    expect(toPersonaGenderOption("other")).toBeUndefined();
    expect(toPersonaGenderOption("female")).toBe("female");
  });
});
