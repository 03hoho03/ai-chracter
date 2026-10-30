import { describe, expect, it } from "vitest";

import { isRoomModelMissingFromList, ROOM_CHAT_MODEL_FALLBACK_NOTICE, roomChatModelNotice } from "./roomChatModelNotice";

describe("roomChatModelNotice", () => {
  it("저장한 적 없는 방(기본 모델)에는 띄우지 않는다", () => {
    expect(roomChatModelNotice({ chatModel: undefined, effectiveChatModel: "gemini" })).toBeUndefined();
  });

  it("저장한 모델 그대로 도는 방에는 띄우지 않는다", () => {
    expect(roomChatModelNotice({ chatModel: "opus", effectiveChatModel: "opus" })).toBeUndefined();
    expect(roomChatModelNotice({ chatModel: "gemini", effectiveChatModel: "gemini" })).toBeUndefined();
  });

  // 목록에서 뺀 모델과 서버가 더는 모르는 옛 값 모두 서버가 기본 모델로 돌린다.
  it("저장한 모델과 서버가 정한 실제 모델이 다르면 띄운다", () => {
    expect(roomChatModelNotice({ chatModel: "opus", effectiveChatModel: "gemini" })).toBe(
      ROOM_CHAT_MODEL_FALLBACK_NOTICE,
    );
    expect(roomChatModelNotice({ chatModel: "retired-model", effectiveChatModel: "gemini" })).toBe(
      ROOM_CHAT_MODEL_FALLBACK_NOTICE,
    );
  });

  // 판정은 계정을 보지 않으므로 계정 탓으로 읽히는 말을 하지 않는다.
  it("문장이 계정을 말하지 않는다", () => {
    expect(ROOM_CHAT_MODEL_FALLBACK_NOTICE).not.toContain("계정");
  });
});

describe("isRoomModelMissingFromList", () => {
  const models = [{ id: "gemini" }, { id: "opus" }] as const;

  it("방의 실제 모델이 목록에 있으면 거짓이다", () => {
    expect(isRoomModelMissingFromList(models, "opus")).toBe(false);
  });

  it("방의 실제 모델이 목록에 없으면 참이다 — 방 상세를 새로 받아야 한다", () => {
    expect(isRoomModelMissingFromList([{ id: "gemini" }], "opus")).toBe(true);
  });
});
