import { createStore } from "jotai";
import { describe, expect, it } from "vitest";

import { DEFAULT_READER_SETTINGS, readerSettingsAtom, readerSettingsSchema } from "./readerSettings";

describe("readerSettingsSchema", () => {
  it("올바른 값을 그대로 통과시킨다", () => {
    const value = { fontSize: "large", lineHeight: "loose", margin: "wide", mode: "scroll", keepScreenOn: true };

    expect(readerSettingsSchema.parse(value)).toEqual(value);
  });

  it("깨진 칸만 기본값으로 돌리고 나머지 고른 값은 지킨다", () => {
    expect(
      readerSettingsSchema.parse({ fontSize: "huge", lineHeight: "loose", mode: "book", keepScreenOn: "yes" }),
    ).toEqual({
      fontSize: DEFAULT_READER_SETTINGS.fontSize,
      lineHeight: "loose",
      margin: DEFAULT_READER_SETTINGS.margin,
      mode: DEFAULT_READER_SETTINGS.mode,
      keepScreenOn: DEFAULT_READER_SETTINGS.keepScreenOn,
    });
  });

  it("넘김 방식·화면 유지 칸이 없던 옛 저장값은 고른 세 칸을 지키고 새 칸만 기본값(페이지·끔)으로 채운다", () => {
    expect(readerSettingsSchema.parse({ fontSize: "large", lineHeight: "loose", margin: "wide" })).toEqual({
      fontSize: "large",
      lineHeight: "loose",
      margin: "wide",
      mode: "page",
      keepScreenOn: false,
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
