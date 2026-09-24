import { describe, expect, it } from "vitest";

import type { Persona, PersonaList } from "@/entities/persona";

import { previewPersonaLabel } from "./previewPersonaLabel";

const MOGWA: Persona = {
  id: "4a1f0b3e-0000-4000-8000-000000000001",
  name: "모과",
  gender: "male",
  description: "새벽 택배 상하차",
  createdAt: "2026-09-24T00:00:00Z",
  updatedAt: "2026-09-24T00:00:00Z",
};

function list(overrides: Partial<PersonaList>): PersonaList {
  return { items: [MOGWA], defaultPersonaId: null, maxCount: 10, ...overrides };
}

describe("previewPersonaLabel", () => {
  // 로딩·에러에는 무엇이 들어가는지 모른다 — 틀린 정보를 보이느니 숨긴다(persona-progress.md S8 ⚪-3).
  it("hides the label while the list is unknown", () => {
    expect(previewPersonaLabel(undefined)).toBeUndefined();
  });

  it("names the default persona the preview turn will use", () => {
    expect(previewPersonaLabel(list({ defaultPersonaId: MOGWA.id }))).toBe("대화 프로필: 모과");
  });

  it("says the preview runs without a persona when there is no default", () => {
    expect(previewPersonaLabel(list({ defaultPersonaId: null }))).toBe("대화 프로필 없이 진행");
  });

  // 목록과 기본 id가 어긋난 응답(있어선 안 되는 상태)에서 "없이 진행"이라고 말하면 거짓일 수 있다.
  it("hides the label when the default id is not in the list", () => {
    expect(previewPersonaLabel(list({ defaultPersonaId: "4a1f0b3e-0000-4000-8000-000000000999" }))).toBeUndefined();
  });
});
