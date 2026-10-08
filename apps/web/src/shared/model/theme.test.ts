import { describe, expect, it } from "vitest";

import { readStoredTheme, writeStoredTheme } from "./theme";

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

describe("readStoredTheme", () => {
  it('"light" 일 때만 라이트, 없거나 모르는 값은 다크', () => {
    expect(readStoredTheme(() => memoryStorage({ theme: "light" }))).toBe("light");
    expect(readStoredTheme(() => memoryStorage({ theme: "dark" }))).toBe("dark");
    expect(readStoredTheme(() => memoryStorage())).toBe("dark");
    expect(readStoredTheme(() => memoryStorage({ theme: "sepia" }))).toBe("dark");
  });

  it("저장소 접근이 막혀 던지면 다크로 시작한다", () => {
    expect(readStoredTheme(blocked)).toBe("dark");
    expect(
      readStoredTheme(() => ({
        getItem: () => {
          throw new Error("blocked");
        },
        setItem: () => undefined,
      })),
    ).toBe("dark");
  });
});

describe("writeStoredTheme", () => {
  it("고른 테마를 저장한다", () => {
    const storage = memoryStorage();
    writeStoredTheme("light", () => storage);
    expect(storage.values.get("theme")).toBe("light");
  });

  it("저장소가 막혀도 던지지 않는다", () => {
    expect(() => writeStoredTheme("light", blocked)).not.toThrow();
  });
});
