export const chatRoomKeys = {
  all: ["chat-room"] as const,
  // 목록은 콘텐츠 단위(같은 캐릭터/스토리)로 스코프된다.
  list: (params: { contentId: string; contentType: "character" | "story" }) =>
    [...chatRoomKeys.all, "list", params] as const,
  // 헤더 "내 채팅목록"용 — 콘텐츠 스코프 없는 전체 목록. `list(params)`와 별개 키라 서로의 invalidate가 겹치지 않는다.
  myList: () => [...chatRoomKeys.all, "my-list"] as const,
  // 대화 프로필 삭제가 여러 방의 `personaId`를 서버에서 NULL로 바꾸므로
  // 방 상세를 한꺼번에 invalidate할 접두 키가 필요하다.
  details: () => [...chatRoomKeys.all, "detail"] as const,
  detail: (roomId: string) => [...chatRoomKeys.details(), roomId] as const,
  playGuide: (roomId: string) => [...chatRoomKeys.all, "play-guide", roomId] as const,
  endingCollection: (startingSetupId: string) =>
    [...chatRoomKeys.all, "ending-collection", startingSetupId] as const,
};
