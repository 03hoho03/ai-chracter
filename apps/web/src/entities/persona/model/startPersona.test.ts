import { describe, expect, it } from "vitest";

import type { Persona, PersonaList } from "./persona";
import { resolveStartPersona } from "./startPersona";

function persona(id: string): Persona {
  return { id, name: id, gender: null, description: "", createdAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z" };
}

/** 목록은 생성순이다 — `oldest` 가 가장 먼저 만든 것. */
function listWith(defaultPersonaId: string | null, ids: string[] = ["oldest", "middle", "newest"]): PersonaList {
  return { items: ids.map(persona), defaultPersonaId, maxCount: 10 };
}

describe("resolveStartPersona", () => {
  it("starts with the default profile when nothing was chosen", () => {
    expect(resolveStartPersona(listWith("middle"))?.id).toBe("middle");
  });

  it("starts with the chosen profile over the default", () => {
    expect(resolveStartPersona(listWith("middle"), "newest")?.id).toBe("newest");
  });

  // 기본이 비어 있는 예전 계정 — 서버가 방을 만들며 기본으로 올릴 프로필을 미리 보인다.
  it("falls back to the oldest profile when the default is empty", () => {
    expect(resolveStartPersona(listWith(null))?.id).toBe("oldest");
  });

  it("falls back to the default when the chosen profile was deleted", () => {
    expect(resolveStartPersona(listWith("middle"), "gone")?.id).toBe("middle");
  });

  it("falls back to the oldest when both the choice and the default are gone", () => {
    expect(resolveStartPersona(listWith("gone-default"), "gone")?.id).toBe("oldest");
  });

  it.each([
    ["no list yet", undefined],
    ["no profiles", listWith(null, [])],
  ] as const)("is null with %s", (_label, list) => {
    expect(resolveStartPersona(list, "anything")).toBeNull();
  });
});
