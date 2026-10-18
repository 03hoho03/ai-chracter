import { describe, expect, it } from "vitest";

import { readStatusLineCollapsed, writeStatusLineCollapsed } from "./statusLineCollapse";

function memoryStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    values,
  };
}

const blocked = () => {
  throw new DOMException("The operation is insecure.", "SecurityError");
};

describe("readStatusLineCollapsed / writeStatusLineCollapsed", () => {
  it("저장값이 없으면 펼침이고, 쓴 값을 그대로 읽는다", () => {
    const storage = memoryStorage();
    expect(readStatusLineCollapsed(() => storage)).toBe(false);
    writeStatusLineCollapsed(true, () => storage);
    expect(readStatusLineCollapsed(() => storage)).toBe(true);
    writeStatusLineCollapsed(false, () => storage);
    expect(readStatusLineCollapsed(() => storage)).toBe(false);
  });

  it("기기에 값 하나만 둔다 — 방마다 키를 따로 만들지 않는다", () => {
    const storage = memoryStorage();
    writeStatusLineCollapsed(true, () => storage);
    expect([...storage.values.keys()]).toEqual(["ttona.chatStatusLine.collapsed"]);
  });

  it("알 수 없는 저장값은 펼침으로 본다", () => {
    expect(readStatusLineCollapsed(() => memoryStorage({ "ttona.chatStatusLine.collapsed": "yes" }))).toBe(false);
  });

  it("저장소가 막혀도 던지지 않고 펼침으로 그린다", () => {
    expect(readStatusLineCollapsed(blocked)).toBe(false);
    expect(() => writeStatusLineCollapsed(true, blocked)).not.toThrow();
  });
});
