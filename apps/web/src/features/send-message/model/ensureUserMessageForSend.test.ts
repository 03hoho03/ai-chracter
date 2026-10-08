import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { buildEditPayload, buildRegeneratePayload, buildSendPayload, chatRoomKeys } from "@/entities/chat-room";
import type { ChatMessage, ChatRoomState } from "@/entities/chat-room";

import { ensureUserMessageForSend } from "./ensureUserMessageForSend";

const ROOM_ID = "room-1";
const SERVER_MESSAGES: ChatMessage[] = [
  { id: "m1", role: "user", content: "안녕", createdAt: "2026-10-04T00:00:00Z" },
  { id: "m2", role: "assistant", content: "반가워", createdAt: "2026-10-04T00:01:00Z" },
];

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
    turnCount: 1,
    defaultUserName: "",
    latestVersionAvailable: false,
    versionAutoUpgraded: false,
    contentRestricted: false,
    novelCreationBlocked: false,
    effectiveChatModel: "gemini",
    turnCost: 10,
    hasMoreMessagesBefore: false,
  };
}

function cachedMessages(queryClient: QueryClient): ChatMessage[] | undefined {
  return queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID))?.messages;
}

describe("ensureUserMessageForSend", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient();
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState(SERVER_MESSAGES));
  });

  it("보내기가 거절된 사이 재조회가 낙관적 메시지를 지웠으면 다시 보내기가 말풍선을 다시 붙인다", () => {
    // 서버는 거절한 메시지를 저장하지 않았으므로, 탭 복귀 재조회 뒤 캐시에는 그 메시지가 없다.
    ensureUserMessageForSend(queryClient, ROOM_ID, buildSendPayload({ roomId: ROOM_ID, text: "탕 온도는?" }));

    const messages = cachedMessages(queryClient);
    expect(messages).toHaveLength(3);
    expect(messages?.at(-1)).toMatchObject({ role: "user", content: "탕 온도는?" });
  });

  it("같은 글의 사용자 메시지가 이미 끝에 있으면 두 번 붙이지 않는다", () => {
    const payload = buildSendPayload({ roomId: ROOM_ID, text: "탕 온도는?" });

    ensureUserMessageForSend(queryClient, ROOM_ID, payload);
    ensureUserMessageForSend(queryClient, ROOM_ID, payload);

    expect(cachedMessages(queryClient)).toHaveLength(3);
  });

  it("끝의 사용자 메시지가 다른 글이면(다른 창에서 보낸 앞 턴) 내 글을 그 뒤에 붙인다", () => {
    const otherTab: ChatMessage = { id: "m3", role: "user", content: "이곳의 역사는?", createdAt: "2026-10-04T00:02:00Z" };
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState([...SERVER_MESSAGES, otherTab]));

    ensureUserMessageForSend(queryClient, ROOM_ID, buildSendPayload({ roomId: ROOM_ID, text: "탕 온도는?" }));

    expect(cachedMessages(queryClient)?.map((message) => message.content)).toEqual([
      "안녕",
      "반가워",
      "이곳의 역사는?",
      "탕 온도는?",
    ]);
  });

  it("수정·재생성은 새 사용자 메시지를 만들지 않으므로 캐시를 건드리지 않는다", () => {
    ensureUserMessageForSend(queryClient, ROOM_ID, buildRegeneratePayload({ roomId: ROOM_ID }));
    ensureUserMessageForSend(
      queryClient,
      ROOM_ID,
      buildEditPayload({ roomId: ROOM_ID, messageId: "m1", text: "안녕하세요" }),
    );

    expect(cachedMessages(queryClient)).toEqual(SERVER_MESSAGES);
  });
});
