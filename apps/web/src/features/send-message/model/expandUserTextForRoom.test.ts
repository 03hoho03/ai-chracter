import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { chatRoomKeys, type ChatRoomState } from "@/entities/chat-room";

import { expandUserTextForRoom } from "./expandUserTextForRoom";

const ROOM_ID = "room-1";

function buildRoom(overrides: Partial<ChatRoomState> = {}): ChatRoomState {
  return {
    id: ROOM_ID,
    contentId: "story-1",
    contentType: "story",
    name: "대화 1",
    messages: [],
    openingMediaTagImages: {},
    stats: {},
    endingStatus: { reached: false },
    turnCount: 0,
    defaultUserName: "",
    latestVersionAvailable: false,
    versionAutoUpgraded: false,
    contentRestricted: false,
    novelCreationBlocked: false,
    effectiveChatModel: "gemini",
    turnCost: 10,
    hasMoreMessagesBefore: false,
    ...overrides,
  };
}

function clientWith(room: ChatRoomState): QueryClient {
  const queryClient = new QueryClient();
  queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), room);
  return queryClient;
}

describe("expandUserTextForRoom", () => {
  // 추천 답변·단축어 프롬프트는 작가 글이라 `{{user}}` 가 들어 있을 수 있다 — 보내기 전에 바꿔야 대화 기록에 이름이 남는다.
  it("puts the room's profile name in before the text is sent, fixing the particle", () => {
    const queryClient = clientWith(buildRoom({ personaName: "지훈", defaultUserName: "조감독" }));
    expect(expandUserTextForRoom(queryClient, ROOM_ID, "{{user}}는 고개를 끄덕인다.")).toBe("지훈은 고개를 끄덕인다.");
  });

  it("uses the work's default name when the room has no profile", () => {
    const queryClient = clientWith(buildRoom({ defaultUserName: "조감독" }));
    expect(expandUserTextForRoom(queryClient, ROOM_ID, "나는 {{user}}야")).toBe("나는 조감독아");
  });

  it("names {{char}} in a character room and leaves it as written in a story room", () => {
    const character = clientWith(buildRoom({ contentType: "character", contentName: "유나" }));
    const story = clientWith(buildRoom({ contentName: "상영회까지" }));
    expect(expandUserTextForRoom(character, ROOM_ID, "{{char}}에게 묻는다")).toBe("유나에게 묻는다");
    expect(expandUserTextForRoom(story, ROOM_ID, "{{char}}에게 묻는다")).toBe("{{char}}에게 묻는다");
  });

  it("returns the text unchanged when the room is not in the cache", () => {
    expect(expandUserTextForRoom(new QueryClient(), ROOM_ID, "{{user}}")).toBe("{{user}}");
  });
});
