import { describe, expect, it } from "vitest";

import { toChatRoomMemory } from "./toChatRoomMemory";

const LIMITS = { noteMaxLength: 1000, summaryMaxLength: 1500 };

describe("toChatRoomMemory", () => {
  it("turns the server's nulls into missing values", () => {
    const memory = toChatRoomMemory({ note: "", summary: null, version: 0, rolledBackAt: null, limits: LIMITS });
    expect(memory.summary).toBeUndefined();
    expect(memory.rolledBackAt).toBeUndefined();
  });

  it("keeps a present summary and rollback time as they are", () => {
    const summary = { text: "둘은 처음 만났다.", source: "user" as const, canRevert: true, updatedAt: "2026-09-28T00:00:00Z" };
    expect(
      toChatRoomMemory({ note: "고양이", summary, version: 3, rolledBackAt: "2026-09-28T01:00:00Z", limits: LIMITS }),
    ).toEqual({ note: "고양이", summary, version: 3, rolledBackAt: "2026-09-28T01:00:00Z", limits: LIMITS });
  });
});
