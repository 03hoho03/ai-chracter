import { describe, expect, it } from "vitest";

import { defaultPersonaName, type PersonaList } from "./persona";

function listWith(defaultPersonaId: string | null): PersonaList {
  return {
    items: [
      { id: "p1", name: "지훈", gender: null, description: "", createdAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z" },
      { id: "p2", name: "하늘", gender: null, description: "", createdAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z" },
    ],
    defaultPersonaId,
    maxCount: 10,
  };
}

describe("defaultPersonaName", () => {
  it("is the default profile's name", () => {
    expect(defaultPersonaName(listWith("p2"))).toBe("하늘");
  });

  // 이름이 없으면 작가 글의 `{{user}}` 는 작품 기본 이름으로 넘어간다.
  it.each([
    ["no list yet", undefined],
    ["no default profile", listWith(null)],
    ["a default id missing from the list", listWith("gone")],
  ] as const)("is null with %s", (_label, list) => {
    expect(defaultPersonaName(list)).toBeNull();
  });
});
