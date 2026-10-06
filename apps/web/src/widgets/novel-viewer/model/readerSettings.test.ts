import { createStore } from "jotai";
import { describe, expect, it } from "vitest";

import { DEFAULT_READER_SETTINGS, readerSettingsAtom, readerSettingsSchema } from "./readerSettings";

describe("readerSettingsSchema", () => {
  it("올바른 값을 그대로 통과시킨다", () => {
    const value = { fontSize: "large", lineHeight: "loose", margin: "wide" };

    expect(readerSettingsSchema.parse(value)).toEqual(value);
  });

  it("깨진 칸만 기본값으로 돌리고 나머지 고른 값은 지킨다", () => {
    expect(readerSettingsSchema.parse({ fontSize: "huge", lineHeight: "loose" })).toEqual({
      fontSize: DEFAULT_READER_SETTINGS.fontSize,
      lineHeight: "loose",
      margin: DEFAULT_READER_SETTINGS.margin,
    });
  });

  it("객체가 아니면 실패한다(저장소가 통째로 기본값을 쓴다)", () => {
    expect(readerSettingsSchema.safeParse("large").success).toBe(false);
    expect(readerSettingsSchema.safeParse(null).success).toBe(false);
  });
});

// atom 은 모듈 로드 때 저장소를 읽는다. vitest 는 node 환경이라 `window` 가 없는데, 그래도 import 가 던지지 않고
// 기본값으로 시작해야 한다.
describe("readerSettingsAtom", () => {
  it("window 없는 환경에서 기본값으로 시작하고 쓰기가 던지지 않는다", () => {
    const store = createStore();

    expect(store.get(readerSettingsAtom)).toEqual(DEFAULT_READER_SETTINGS);

    store.set(readerSettingsAtom, { ...DEFAULT_READER_SETTINGS, fontSize: "large" });

    expect(store.get(readerSettingsAtom).fontSize).toBe("large");
  });
});
