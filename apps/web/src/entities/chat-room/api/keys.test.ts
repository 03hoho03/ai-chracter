import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { chatRoomKeys } from "./keys";

const SCOPED_LIST = chatRoomKeys.list({ contentId: "c", contentType: "character" });

function seededClient() {
  const queryClient = new QueryClient();
  queryClient.setQueryData(chatRoomKeys.myList("viewer-a"), ["a-all"]);
  queryClient.setQueryData(chatRoomKeys.myRecentList("viewer-a", 10), ["a-recent"]);
  queryClient.setQueryData(chatRoomKeys.myList("viewer-b"), ["b-all"]);
  queryClient.setQueryData(chatRoomKeys.myRecentList("viewer-b", 10), ["b-recent"]);
  queryClient.setQueryData(SCOPED_LIST, ["scoped"]);
  queryClient.setQueryData(chatRoomKeys.detail("room-1"), { id: "room-1" });
  return queryClient;
}

const cachedData = (queryClient: QueryClient, queryKey: readonly unknown[]) =>
  queryClient
    .getQueryCache()
    .findAll({ queryKey })
    .map((query) => query.state.data);

describe("chatRoomKeys 내 방 목록", () => {
  it("공통 접두 하나가 모든 계정의 전체 목록과 최근 목록을 덮고, 콘텐츠 스코프 목록·방 상세는 덮지 않는다", () => {
    const queryClient = seededClient();
    expect(cachedData(queryClient, chatRoomKeys.myLists())).toEqual([
      ["a-all"],
      ["a-recent"],
      ["b-all"],
      ["b-recent"],
    ]);
  });

  it("한 계정의 전체 목록 키는 그 계정의 최근 목록만 함께 덮고 다른 계정의 것은 덮지 않는다", () => {
    const queryClient = seededClient();
    expect(cachedData(queryClient, chatRoomKeys.myList("viewer-b"))).toEqual([["b-all"], ["b-recent"]]);
  });

  it("다른 계정으로 로그인하면 같은 목록이라도 키가 달라 이전 계정의 캐시를 읽지 못한다", () => {
    const queryClient = seededClient();
    expect(queryClient.getQueryData(chatRoomKeys.myList("viewer-c"))).toBeUndefined();
    expect(queryClient.getQueryData(chatRoomKeys.myRecentList("viewer-c", 10))).toBeUndefined();
  });

  it("로그아웃 정리는 공통 접두로 모든 계정의 내 방 목록을 지우고 다른 캐시는 남긴다", () => {
    const queryClient = seededClient();
    queryClient.removeQueries({ queryKey: chatRoomKeys.myLists() });
    expect(cachedData(queryClient, chatRoomKeys.myLists())).toEqual([]);
    expect(queryClient.getQueryData(SCOPED_LIST)).toEqual(["scoped"]);
    expect(queryClient.getQueryData(chatRoomKeys.detail("room-1"))).toEqual({ id: "room-1" });
  });
});
