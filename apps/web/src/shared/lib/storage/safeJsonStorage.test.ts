import { describe, expect, it } from "vitest";
import { z } from "zod";

import { createSafeJsonStorage } from "./safeJsonStorage";

const schema = z.object({ size: z.enum(["small", "large"]) });
const INITIAL: z.infer<typeof schema> = { size: "small" };

function memoryStorage(entries: Record<string, string> = {}) {
  const map = new Map(Object.entries(entries));
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => {
      map.set(key, value);
    },
    removeItem: (key: string) => {
      map.delete(key);
    },
  };
}

function throwingStorage() {
  return {
    getItem: (): string | null => {
      throw new Error("SecurityError");
    },
    setItem: () => {
      throw new Error("QuotaExceededError");
    },
    removeItem: () => {
      throw new Error("SecurityError");
    },
  };
}

describe("createSafeJsonStorage", () => {
  it("저장된 값이 스키마를 통과하면 그 값을 돌려준다", () => {
    const storage = createSafeJsonStorage(schema, () => memoryStorage({ key: '{"size":"large"}' }));

    expect(storage.getItem("key", INITIAL)).toEqual({ size: "large" });
  });

  it("쓴 값을 다시 읽는다", () => {
    const backing = memoryStorage();
    const storage = createSafeJsonStorage(schema, () => backing);

    storage.setItem("key", { size: "large" });

    expect(storage.getItem("key", INITIAL)).toEqual({ size: "large" });
  });

  it("저장된 값이 없으면 초기값", () => {
    const storage = createSafeJsonStorage(schema, () => memoryStorage());

    expect(storage.getItem("key", INITIAL)).toBe(INITIAL);
  });

  it("스키마에 맞지 않는 값이면 초기값", () => {
    const storage = createSafeJsonStorage(schema, () => memoryStorage({ key: '{"size":"huge"}' }));

    expect(storage.getItem("key", INITIAL)).toBe(INITIAL);
  });

  it("JSON 이 깨졌으면 초기값", () => {
    const storage = createSafeJsonStorage(schema, () => memoryStorage({ key: "{not json" }));

    expect(storage.getItem("key", INITIAL)).toBe(INITIAL);
  });

  it("읽기·쓰기·지우기가 던지는 저장소에서도 예외를 내지 않는다", () => {
    const storage = createSafeJsonStorage(schema, throwingStorage);

    expect(storage.getItem("key", INITIAL)).toBe(INITIAL);
    expect(() => storage.setItem("key", { size: "large" })).not.toThrow();
    expect(() => storage.removeItem("key")).not.toThrow();
  });

  // vitest 환경이 node 라 기본 저장소 getter 가 실제로 `window` 없는 경로를 탄다.
  it("window 가 없는 환경에서 기본 저장소로 만들어도 초기값을 돌려주고 쓰기가 던지지 않는다", () => {
    expect(typeof window).toBe("undefined");
    const storage = createSafeJsonStorage(schema);

    expect(storage.getItem("key", INITIAL)).toBe(INITIAL);
    expect(() => storage.setItem("key", { size: "large" })).not.toThrow();
    expect(() => storage.removeItem("key")).not.toThrow();
  });
});
