import { describe, expect, it } from "vitest";

import type { PersonaList } from "@/entities/persona";

import { previewAuthorMacroNames } from "./previewAuthorMacroNames";

const PERSONAS: PersonaList = {
  items: [
    {
      id: "p1",
      name: "모과",
      gender: null,
      description: "",
      createdAt: "2026-09-24T00:00:00Z",
      updatedAt: "2026-09-24T00:00:00Z",
    },
  ],
  defaultPersonaId: "p1",
  maxCount: 10,
};

describe("previewAuthorMacroNames", () => {
  // 서버는 미리보기 턴마다 작가의 현재 기본 프로필을 쓴다 — 화면도 같은 이름이어야 한다.
  it("uses the author's default profile", () => {
    expect(previewAuthorMacroNames({ contentName: "유나" }, "character", PERSONAS)).toEqual({
      userName: "모과",
      charName: "유나",
    });
  });

  it("uses the fallback name while the profile list is unknown or has no default", () => {
    const source = { contentName: "유나" };
    expect(previewAuthorMacroNames(source, "character", undefined).userName).toBe("당신");
    expect(previewAuthorMacroNames(source, "character", { ...PERSONAS, defaultPersonaId: null }).userName).toBe("당신");
  });

  it("leaves {{char}} for a story preview", () => {
    expect(previewAuthorMacroNames({ contentName: "항해" }, "story", undefined).charName).toBeNull();
  });
});
