import { describe, expect, it } from "vitest";

import {
  getNextScreenCollapsed,
  getSidePanelScreen,
  parseSidePanelCollapsed,
  readSavedSidePanelCollapsed,
  resolveSidePanelCollapsed,
  toggleSidePanelCollapsed,
  writeSavedSidePanelCollapsed,
} from "./sidePanelCollapse";

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

describe("getSidePanelScreen", () => {
  it("채팅방과 이미지 스튜디오만 따로 가르고 나머지는 기타다", () => {
    expect(getSidePanelScreen("/chat/room-1")).toBe("chat");
    expect(getSidePanelScreen("/studio/images")).toBe("image-studio");
    for (const pathname of ["/", "/chats", "/chat", "/chat/room-1/extra", "/studio", "/studio/images/extra", "/my"]) {
      expect(getSidePanelScreen(pathname)).toBe("other");
    }
  });
});

describe("getNextScreenCollapsed", () => {
  it("바깥에서 채팅·이미지 스튜디오로 들어오면 접힘으로 시작한다(처음 그리는 화면 포함)", () => {
    expect(getNextScreenCollapsed("other", "chat", undefined)).toBe(true);
    expect(getNextScreenCollapsed(undefined, "chat", undefined)).toBe(true);
    expect(getNextScreenCollapsed("other", "image-studio", undefined)).toBe(true);
  });

  it("채팅에서 다른 채팅으로 옮기면 그 화면에서 바꾼 임시값을 이어 간다", () => {
    expect(getNextScreenCollapsed("chat", "chat", false)).toBe(false);
    expect(getNextScreenCollapsed("chat", "chat", true)).toBe(true);
  });

  it("채팅에서 이미지 스튜디오로 가면 다른 화면에 들어온 것이라 접힘으로 시작한다", () => {
    expect(getNextScreenCollapsed("chat", "image-studio", false)).toBe(true);
    expect(getNextScreenCollapsed("image-studio", "chat", false)).toBe(true);
  });

  it("채팅·이미지 스튜디오를 떠나면 임시값을 잊는다", () => {
    expect(getNextScreenCollapsed("chat", "other", false)).toBeUndefined();
    expect(getNextScreenCollapsed("image-studio", "other", true)).toBeUndefined();
  });
});

describe("resolveSidePanelCollapsed", () => {
  it("저장값이 없으면 xl 이상은 펼침, 그 아래는 접힘이다", () => {
    expect(resolveSidePanelCollapsed({ savedCollapsed: undefined, screenCollapsed: undefined, isWide: true })).toBe(false);
    expect(resolveSidePanelCollapsed({ savedCollapsed: undefined, screenCollapsed: undefined, isWide: false })).toBe(true);
  });

  it("저장값은 폭과 무관하게 폭 기본값을 이긴다", () => {
    expect(resolveSidePanelCollapsed({ savedCollapsed: false, screenCollapsed: undefined, isWide: false })).toBe(false);
    expect(resolveSidePanelCollapsed({ savedCollapsed: true, screenCollapsed: undefined, isWide: true })).toBe(true);
  });

  it("펼침을 저장했어도 바깥에서 채팅에 들어오면 접혀 있다", () => {
    const screenCollapsed = getNextScreenCollapsed("other", "chat", undefined);
    expect(resolveSidePanelCollapsed({ savedCollapsed: false, screenCollapsed, isWide: true })).toBe(true);
  });

  it("채팅에서 펼친 것은 그 화면 동안 저장값보다 앞선다", () => {
    expect(resolveSidePanelCollapsed({ savedCollapsed: true, screenCollapsed: false, isWide: false })).toBe(false);
  });
});

describe("toggleSidePanelCollapsed", () => {
  it("채팅·이미지 스튜디오에서 바꾼 것은 저장하지 않는다", () => {
    expect(toggleSidePanelCollapsed("chat", true)).toEqual({ isCollapsed: false, shouldSave: false });
    expect(toggleSidePanelCollapsed("image-studio", false)).toEqual({ isCollapsed: true, shouldSave: false });
  });

  it("그 밖의 화면에서 바꾼 것은 저장한다", () => {
    expect(toggleSidePanelCollapsed("other", true)).toEqual({ isCollapsed: false, shouldSave: true });
    expect(toggleSidePanelCollapsed("other", false)).toEqual({ isCollapsed: true, shouldSave: true });
  });
});

describe("parseSidePanelCollapsed", () => {
  it('"1" 은 접힘, "0" 은 펼침, 모르는 값은 저장값 없음', () => {
    expect(parseSidePanelCollapsed("1")).toBe(true);
    expect(parseSidePanelCollapsed("0")).toBe(false);
    for (const raw of [null, undefined, "", "true", "false", "2"]) {
      expect(parseSidePanelCollapsed(raw)).toBeUndefined();
    }
  });
});

describe("readSavedSidePanelCollapsed / writeSavedSidePanelCollapsed", () => {
  it("쓴 값을 그대로 읽는다", () => {
    const storage = memoryStorage();
    writeSavedSidePanelCollapsed(true, () => storage);
    expect(readSavedSidePanelCollapsed(() => storage)).toBe(true);
    writeSavedSidePanelCollapsed(false, () => storage);
    expect(readSavedSidePanelCollapsed(() => storage)).toBe(false);
  });

  it("저장소가 막혀도 던지지 않고 저장값 없음으로 본다", () => {
    expect(readSavedSidePanelCollapsed(blocked)).toBeUndefined();
    expect(() => writeSavedSidePanelCollapsed(true, blocked)).not.toThrow();
  });
});
