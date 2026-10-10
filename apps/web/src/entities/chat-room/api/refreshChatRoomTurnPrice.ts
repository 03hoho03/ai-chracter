import type { QueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "./keys";
import { fetchChatRoom } from "./useChatRoomQuery";
import type { ChatRoomState } from "../model/chatRoomState";

/** 방을 다시 받아 다음 턴의 모델·가격만 캐시에 고치고 그 가격을 돌려준다.
 *
 * 방 상세 캐시는 모델을 바꿀 때와 탭 복귀 때만 새로 받으므로, 화면을 띄워 둔 사이 운영자가 상위 모델을 끄면 서버는
 * 기본 모델로 돌리는데 화면은 옛 모델의 가격을 들고 있다. 클로버 429 를 받은 순간이 그 어긋남을 드러내는
 * 때라 확인 모달과 부족 안내가 그 뒤의 값을 쓰게 한다.
 *
 * 메시지는 건드리지 않는다 — 시작 전에 거절된 낙관적 사용자 메시지는 서버에 없어서 방 전체를 갈아 끼우면 말풍선이
 * 사라진다. 조회가 실패하면 캐시의 가격을 그대로 돌려준다(모달을 막을 이유는 아니다). */
export async function refreshChatRoomTurnPrice(queryClient: QueryClient, roomId: string): Promise<number | undefined> {
  const key = chatRoomKeys.detail(roomId);
  try {
    const fresh = await fetchChatRoom(queryClient, roomId);
    queryClient.setQueryData<ChatRoomState>(key, (prev) =>
      prev ? { ...prev, effectiveChatModel: fresh.effectiveChatModel, turnCost: fresh.turnCost } : prev,
    );
    return fresh.turnCost;
  } catch {
    return queryClient.getQueryData<ChatRoomState>(key)?.turnCost;
  }
}
