/** 최근 대화 목록이 보여 주는 방 수. 서버에 `limit` 으로도 보낸다. */
export const RECENT_CHAT_ROOM_LIMIT = 10;

/** 서버가 준 최근 활동순 목록의 앞 `RECENT_CHAT_ROOM_LIMIT` 개만 남긴다. `limit` 을 모르는 옛 API 는 그 파라미터를
 * 무시하고 전체를 돌려주므로, 서버 배포 순서와 상관없이 캐시와 화면에 10개만 들어가게 받은 쪽에서도 자른다. */
export function takeRecentChatRooms<T>(items: readonly T[]): T[] {
  return items.slice(0, RECENT_CHAT_ROOM_LIMIT);
}
