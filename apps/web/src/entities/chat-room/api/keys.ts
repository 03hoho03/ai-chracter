export const chatRoomKeys = {
  all: ["chat-room"] as const,
  // 목록은 콘텐츠 단위(같은 캐릭터/스토리)로 스코프된다.
  list: (params: { contentId: string; contentType: "character" | "story" }) =>
    [...chatRoomKeys.all, "list", params] as const,
  // 콘텐츠 스코프 없는 내 방 목록(`/chats` 전체 목록과 최근 대화 목록)의 공통 접두 — 무효화 전용이다.
  // `list(params)`와 별개 키라 서로의 invalidate가 겹치지 않는다. 방이 바뀌는 곳은 이 접두 하나로 두 목록을 함께
  // 갱신한다(로그아웃·탈퇴는 `all` 로 방 캐시 전부를 비운다).
  myLists: () => [...chatRoomKeys.all, "my-list"] as const,
  // 보는 사람 id 를 키에 넣는다 — 세션을 잃은 탭에서 다른 계정으로 로그인하면 키가 달라져, 메모리에 남은 이전
  // 계정의 목록이 새 계정 화면에 한 프레임도 그려지지 않는다(마운트 리페치는 캐시를 먼저 그린 뒤 다시 받는다).
  myList: (viewerId: string) => [...chatRoomKeys.myLists(), viewerId] as const,
  myRecentList: (viewerId: string, limit: number) =>
    [...chatRoomKeys.myList(viewerId), "recent", limit] as const,
  // 대화 프로필 삭제가 여러 방의 `personaId`를 서버에서 NULL로 바꾸므로
  // 방 상세를 한꺼번에 invalidate할 접두 키가 필요하다.
  details: () => [...chatRoomKeys.all, "detail"] as const,
  detail: (roomId: string) => [...chatRoomKeys.details(), roomId] as const,
  // 방 기억(노트·요약)은 `details()` 접두 밖에 둔다 — 대화 프로필 삭제가 방 상세를 접두로 무효화할 때마다
  // 기억까지 다시 받을 이유가 없다.
  memory: (roomId: string) => [...chatRoomKeys.all, "memory", roomId] as const,
  playGuide: (roomId: string) => [...chatRoomKeys.all, "play-guide", roomId] as const,
  endingCollection: (startingSetupId: string) =>
    [...chatRoomKeys.all, "ending-collection", startingSetupId] as const,
};
