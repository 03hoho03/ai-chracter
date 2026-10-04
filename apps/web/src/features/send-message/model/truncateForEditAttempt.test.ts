import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { chatRoomKeys } from "@/entities/chat-room";
import type { ChatMessage, ChatRoomState, ChatStreamRequest } from "@/entities/chat-room";

import { settleTurnInProgress } from "./settleTurnInProgress";
import { truncateForEditAttempt } from "./truncateForEditAttempt";

const ROOM_ID = "room-1";
const MESSAGES: ChatMessage[] = [
  { id: "m1", role: "user", content: "안녕", createdAt: "2026-10-04T00:00:00Z" },
  { id: "m2", role: "assistant", content: "반가워", createdAt: "2026-10-04T00:01:00Z" },
  { id: "m3", role: "user", content: "잘 지내?", createdAt: "2026-10-04T00:02:00Z" },
  { id: "m4", role: "assistant", content: "응 잘 지내", createdAt: "2026-10-04T00:03:00Z" },
];
const EDIT: ChatStreamRequest = { kind: "edit", roomId: ROOM_ID, messageId: "m1", content: "안녕하세요" };
const TURN_IN_PROGRESS = { status: 409, detail: { code: "CHAT_TURN_IN_PROGRESS" }, message: "x" };

function buildState(messages: ChatMessage[]): ChatRoomState {
  return {
    id: ROOM_ID,
    contentId: "character-1",
    contentType: "character",
    name: "대화 1",
    messages,
    openingMediaTagImages: {},
    stats: {},
    endingStatus: { reached: false, endingId: undefined, reachedAtTurn: undefined, epilogue: undefined },
    turnCount: 2,
    defaultUserName: "",
    latestVersionAvailable: false,
    versionAutoUpgraded: false,
    contentRestricted: false,
  };
}

function cachedMessages(queryClient: QueryClient): ChatMessage[] | undefined {
  return queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID))?.messages;
}

describe("truncateForEditAttempt", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient();
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState(MESSAGES));
  });

  it("수정이 다른 오류로 끝난 뒤 다시 보내기가 앞 턴 때문에 거절되면 첫 시도 전 목록으로 되돌린다", () => {
    // 첫 시도: 잘라 두고 서버 오류(500)로 끝난다 — 잘린 목록이 캐시에 남는다.
    const carried = truncateForEditAttempt(queryClient, ROOM_ID, EDIT, undefined);
    expect(cachedMessages(queryClient)).toHaveLength(1);

    // 다시 보내기: 잘린 캐시 위에서 다시 시작하지만 되돌릴 목록은 첫 시도 것을 이어 받는다.
    const retried = truncateForEditAttempt(queryClient, ROOM_ID, EDIT, carried);
    expect(settleTurnInProgress(queryClient, ROOM_ID, TURN_IN_PROGRESS, retried)).toBe(true);

    expect(cachedMessages(queryClient)).toEqual(MESSAGES);
  });

  it("수정이 아니면 캐시를 건드리지 않고 받은 값을 그대로 넘긴다", () => {
    const send: ChatStreamRequest = { kind: "send", roomId: ROOM_ID, content: "또 왔어", shortcutId: null };

    expect(truncateForEditAttempt(queryClient, ROOM_ID, send, undefined)).toBeUndefined();
    expect(cachedMessages(queryClient)).toEqual(MESSAGES);
  });
});
