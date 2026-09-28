import { describe, expect, it } from "vitest";

import { isRollbackUnseen, readSeenRollback, writeSeenRollback } from "./rollbackNotice";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
  };
}

const THROWING_STORAGE = {
  getItem: (): string | null => {
    throw new Error("SecurityError");
  },
  setItem: (): void => {
    throw new Error("QuotaExceededError");
  },
};

describe("isRollbackUnseen", () => {
  it("shows a rollback that was never seen", () => {
    expect(isRollbackUnseen("2026-09-28T10:00:00Z", undefined)).toBe(true);
  });

  it("does not show the same rollback twice", () => {
    expect(isRollbackUnseen("2026-09-28T10:00:00Z", "2026-09-28T10:00:00Z")).toBe(false);
  });

  it("shows again when the rollback time changes", () => {
    expect(isRollbackUnseen("2026-09-28T11:00:00Z", "2026-09-28T10:00:00Z")).toBe(true);
  });

  it("has nothing to show when the room was never rolled back", () => {
    expect(isRollbackUnseen(undefined, undefined)).toBe(false);
  });
});

describe("seen rollback storage", () => {
  it("keeps what was seen per room", () => {
    const storage = memoryStorage();
    writeSeenRollback(storage, "room-a", "2026-09-28T10:00:00Z");
    expect(readSeenRollback(storage, "room-a")).toBe("2026-09-28T10:00:00Z");
    expect(readSeenRollback(storage, "room-b")).toBeUndefined();
  });

  // 사생활 모드·차단된 사이트 데이터에서는 저장소 접근이 던진다 — 패널이 죽지 않고 "본 적 없음"이 된다.
  it("treats a throwing storage as never seen", () => {
    expect(readSeenRollback(THROWING_STORAGE, "room-a")).toBeUndefined();
  });

  it("ignores a throwing storage when writing", () => {
    expect(() => writeSeenRollback(THROWING_STORAGE, "room-a", "2026-09-28T10:00:00Z")).not.toThrow();
  });

  it("treats a missing storage as never seen", () => {
    expect(readSeenRollback(undefined, "room-a")).toBeUndefined();
  });
});
