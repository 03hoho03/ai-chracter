import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { chatRoomKeys, dropLastMessage } from "@/entities/chat-room";
import type { ChatMessage, ChatRoomState } from "@/entities/chat-room";
import { cloverKeys } from "@/entities/clover";

import { settleTurnStreamEnd } from "./settleTurnStreamEnd";

const ROOM_ID = "room-1";
const MESSAGES: ChatMessage[] = [
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

function isStale(queryClient: QueryClient, queryKey: readonly unknown[]): boolean | undefined {
  return queryClient.getQueryState(queryKey)?.isInvalidated;
}

describe("settleTurnStreamEnd", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient();
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState(MESSAGES));
    queryClient.setQueryData(chatRoomKeys.memory(ROOM_ID), { notes: [] });
    queryClient.setQueryData(chatRoomKeys.myList("viewer-1"), { items: [] });
    queryClient.setQueryData(cloverKeys.balance(), { balance: 100 });
  });

  it("재생성이 done 없이 끝나면 지운 옛 답변을 되살리고 방을 다시 받는다", () => {
    const dropped = dropLastMessage(queryClient, ROOM_ID);

    settleTurnStreamEnd(queryClient, ROOM_ID, { dropped, hasCommitted: false });

    expect(cachedMessages(queryClient)).toEqual(MESSAGES);
    expect(isStale(queryClient, chatRoomKeys.detail(ROOM_ID))).toBe(true);
  });

  it("done 을 반영한 뒤에는 방 캐시를 건드리지 않는다", () => {
    const dropped = dropLastMessage(queryClient, ROOM_ID);

    settleTurnStreamEnd(queryClient, ROOM_ID, { dropped, hasCommitted: true });

    expect(cachedMessages(queryClient)).toEqual([MESSAGES[0]]);
    expect(isStale(queryClient, chatRoomKeys.detail(ROOM_ID))).toBe(false);
  });

  it("어떻게 끝나든 기억과 내 방 목록을 낡음으로 표시한다", () => {
    for (const hasCommitted of [true, false]) {
      queryClient.setQueryData(chatRoomKeys.memory(ROOM_ID), { notes: [] });
      queryClient.setQueryData(chatRoomKeys.myList("viewer-1"), { items: [] });

      settleTurnStreamEnd(queryClient, ROOM_ID, { dropped: undefined, hasCommitted });

      expect(isStale(queryClient, chatRoomKeys.memory(ROOM_ID))).toBe(true);
      expect(isStale(queryClient, chatRoomKeys.myList("viewer-1"))).toBe(true);
    }
  });

  it("done 없이 끝난 스트림 뒤에도 클로버 잔액을 낡음으로 표시한다 — 정책 위반으로 소모됐거나 환급됐을 수 있다", () => {
    settleTurnStreamEnd(queryClient, ROOM_ID, { dropped: undefined, hasCommitted: false });

    expect(isStale(queryClient, cloverKeys.balance())).toBe(true);
  });

  it("done 을 반영한 턴 뒤에도 클로버 잔액을 낡음으로 표시한다", () => {
    settleTurnStreamEnd(queryClient, ROOM_ID, { dropped: undefined, hasCommitted: true });

    expect(isStale(queryClient, cloverKeys.balance())).toBe(true);
  });

  // 서버는 수정의 뒤 대화 삭제·스탯 되돌리기·턴 수 감소를 새 답을 만들기 전에 커밋한다. 생성이 실패해도 그 셋은 이미
  // 서버에 있어, 방을 다시 받지 않으면 스탯 게이지와 턴 수가 아무 안내 없이 낡은 채 남는다.
  it("수정이 done 없이 끝나면(스트림 안 오류·끊김) 방을 다시 받는다", () => {
    settleTurnStreamEnd(queryClient, ROOM_ID, { dropped: undefined, hasCommitted: false, isEdit: true });

    expect(isStale(queryClient, chatRoomKeys.detail(ROOM_ID))).toBe(true);
  });

  it("수정이 done 을 반영한 뒤에도 방을 다시 받는다 — 되돌린 스탯은 스트림 이벤트로 다 오지 않는다", () => {
    settleTurnStreamEnd(queryClient, ROOM_ID, { dropped: undefined, hasCommitted: true, isEdit: true });

    expect(isStale(queryClient, chatRoomKeys.detail(ROOM_ID))).toBe(true);
  });

  // 시작 전 거절(재화 부족·앞 턴 진행 중 등)이면 서버는 아무것도 바꾸지 않았다. 다시 받으면 잘라 둔 목록이 서버의 옛 목록으로
  // 돌아가 고쳐 쓴 글이 화면에서 사라진다.
  it("서버가 시작 전에 거절한 수정은 방을 다시 받지 않는다", () => {
    settleTurnStreamEnd(queryClient, ROOM_ID, {
      dropped: undefined,
      hasCommitted: false,
      isEdit: true,
      wasRejected: true,
    });

    expect(isStale(queryClient, chatRoomKeys.detail(ROOM_ID))).toBe(false);
  });

  it("보내기는 done 없이 끝나도 방을 다시 받지 않는다(지금 동작 유지)", () => {
    settleTurnStreamEnd(queryClient, ROOM_ID, { dropped: undefined, hasCommitted: false });

    expect(isStale(queryClient, chatRoomKeys.detail(ROOM_ID))).toBe(false);
  });
});
