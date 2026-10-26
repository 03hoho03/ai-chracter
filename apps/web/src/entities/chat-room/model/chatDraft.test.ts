import { describe, expect, it } from "vitest";

import {
  clearAllChatDrafts,
  clearRejectedChatMessage,
  pickChatDraftToRestore,
  readChatDraft,
  removeChatDraft,
  saveChatDraftInput,
  saveRejectedChatMessage,
} from "./chatDraft";

function memoryStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() {
      return values.size;
    },
    values,
  };
}

const blocked = () => {
  throw new DOMException("The operation is insecure.", "SecurityError");
};

describe("채팅 초안 저장", () => {
  it("방마다 따로 저장하고 읽는다", () => {
    const storage = memoryStorage();
    saveChatDraftInput("room-a", "안녕", () => storage);
    saveChatDraftInput("room-b", "반가워", () => storage);
    expect(readChatDraft("room-a", () => storage)).toEqual({ input: "안녕", rejected: "" });
    expect(readChatDraft("room-b", () => storage)).toEqual({ input: "반가워", rejected: "" });
  });

  it("입력 초안과 거절된 메시지를 함께 두고, 거절된 메시지만 따로 지운다", () => {
    const storage = memoryStorage();
    saveRejectedChatMessage("room-a", "보내려던 말", () => storage);
    saveChatDraftInput("room-a", "새로 쓰는 말", () => storage);
    expect(readChatDraft("room-a", () => storage)).toEqual({ input: "새로 쓰는 말", rejected: "보내려던 말" });
    clearRejectedChatMessage("room-a", () => storage);
    expect(readChatDraft("room-a", () => storage)).toEqual({ input: "새로 쓰는 말", rejected: "" });
  });

  it("둘 다 비면 키를 남기지 않는다", () => {
    const storage = memoryStorage();
    saveChatDraftInput("room-a", "안녕", () => storage);
    saveChatDraftInput("room-a", "", () => storage);
    expect(storage.values.size).toBe(0);
  });

  it("방을 지우면 그 방 초안만 지운다", () => {
    const storage = memoryStorage();
    saveChatDraftInput("room-a", "a", () => storage);
    saveChatDraftInput("room-b", "b", () => storage);
    removeChatDraft("room-a", () => storage);
    expect(readChatDraft("room-a", () => storage)).toBeNull();
    expect(readChatDraft("room-b", () => storage)).not.toBeNull();
  });

  // 같은 탭에서 다른 계정으로 로그인했을 때 앞 계정의 초안이 보이면 안 된다.
  it("전부 지우기는 채팅 초안 키만 지우고 다른 값은 남긴다", () => {
    const storage = memoryStorage({ other: "keep" });
    saveChatDraftInput("room-a", "a", () => storage);
    saveRejectedChatMessage("room-b", "b", () => storage);
    clearAllChatDrafts(() => storage);
    expect([...storage.values.keys()]).toEqual(["other"]);
  });

  it("깨진 저장값은 없는 것으로 읽는다", () => {
    const storage = memoryStorage();
    saveChatDraftInput("room-a", "a", () => storage);
    const [key = ""] = storage.values.keys();
    storage.values.set(key, "{not json");
    expect(readChatDraft("room-a", () => storage)).toBeNull();
    storage.values.set(key, JSON.stringify({ input: 1 }));
    expect(readChatDraft("room-a", () => storage)).toBeNull();
  });

  it("저장소가 막혀도 던지지 않는다", () => {
    expect(readChatDraft("room-a", blocked)).toBeNull();
    expect(() => saveChatDraftInput("room-a", "a", blocked)).not.toThrow();
    expect(() => saveRejectedChatMessage("room-a", "a", blocked)).not.toThrow();
    expect(() => clearRejectedChatMessage("room-a", blocked)).not.toThrow();
    expect(() => removeChatDraft("room-a", blocked)).not.toThrow();
    expect(() => clearAllChatDrafts(blocked)).not.toThrow();
  });
});

describe("pickChatDraftToRestore", () => {
  it("저장값이 없으면 되살릴 글이 없다", () => {
    expect(pickChatDraftToRestore(null)).toBe("");
  });

  it("입력 초안이 없으면 거절된 메시지를 되살린다", () => {
    expect(pickChatDraftToRestore({ input: "", rejected: "보내려던 말" })).toBe("보내려던 말");
  });

  // 거절된 메시지는 보낼 때 입력창을 비운 뒤에 생기므로, 입력 초안이 있다면 그 뒤에 새로 쓴 글이다.
  it("입력 초안이 있으면 거절된 메시지로 덮지 않는다", () => {
    expect(pickChatDraftToRestore({ input: "새로 쓰는 말", rejected: "보내려던 말" })).toBe("새로 쓰는 말");
  });

  it("공백뿐인 입력 초안은 없는 것으로 본다", () => {
    expect(pickChatDraftToRestore({ input: "  \n", rejected: "보내려던 말" })).toBe("보내려던 말");
  });
});
