import type { components } from "@ai-character-chat/api-types";
import { describe, expect, it } from "vitest";

import type { PersonaList } from "@/entities/persona";

import { previewAuthorMacroNames } from "./previewAuthorMacroNames";

type CharacterDraftPayload = components["schemas"]["CharacterDraftPayload"];

function characterPayload(overrides: Partial<CharacterDraftPayload> = {}): CharacterDraftPayload {
  return {
    name: "유나",
    oneLiner: "",
    thumbnailAssetId: null,
    intro: "{{user}}, 왔어?",
    exampleDialogues: [],
    characterPrompt: "",
    playguide: null,
    situationalImages: [],
    description: "",
    genreId: null,
    target: null,
    hashtags: [],
    visibility: "public",
    ...overrides,
  };
}

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
  it("uses the author's default profile before the work's default name", () => {
    expect(previewAuthorMacroNames(characterPayload({ defaultUserName: "막내" }), "character", PERSONAS)).toEqual({
      userName: "모과",
      charName: "유나",
    });
  });

  it("uses the work's default name typed in the form while the profile list is unknown or has no default", () => {
    const payload = characterPayload({ defaultUserName: "막내" });
    expect(previewAuthorMacroNames(payload, "character", undefined).userName).toBe("막내");
    expect(previewAuthorMacroNames(payload, "character", { ...PERSONAS, defaultPersonaId: null }).userName).toBe("막내");
  });

  it("falls back to the fallback name when the form has no default name either", () => {
    expect(previewAuthorMacroNames(characterPayload(), "character", undefined).userName).toBe("당신");
  });
});
