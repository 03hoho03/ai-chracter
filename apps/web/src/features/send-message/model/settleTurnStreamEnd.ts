import type { QueryClient } from "@tanstack/react-query";

import { chatRoomKeys, restoreMessage } from "@/entities/chat-room";
import type { ChatMessage } from "@/entities/chat-room";

type TurnStreamEnd = {
  /** 재생성이 스트림 전에 화면에서 지운 옛 답변. 재생성이 아니거나 지운 게 없으면 없다. */
  dropped: ChatMessage | undefined;
  /** `done`을 방 캐시에 반영했는가("봤다"가 아니다 — 방 캐시가 없으면 반영도 없다). */
  hasCommitted: boolean;
};

/** 채팅 턴 스트림이 어떻게 끝나든(성공·스트림 안 오류·예외·끊김) 마지막에 한 번 부르는 캐시 정리다. */
export function settleTurnStreamEnd(
  queryClient: QueryClient,
  roomId: string,
  { dropped, hasCommitted }: TurnStreamEnd,
): void {
  // 동기 롤백 + invalidate 둘 다. 롤백만으로는 서버가 실제로 커밋한 경우 화면이 서버와
  // 어긋난 채 남고, invalidate만으로는 왕복 동안 메시지가 빠진 화면이 유지된다.
  if (dropped && !hasCommitted) {
    restoreMessage(queryClient, roomId, dropped);
    void queryClient.invalidateQueries({ queryKey: chatRoomKeys.detail(roomId) });
  }
  // 기억(노트·요약)은 스트림 이벤트로 오지 않으므로 끝날 때마다 낡음 표시만 한다. 편집·재생성의 요약
  // 되감기는 스트림 전에 커밋되므로 여기서 잡힌다 — `done` 없이 끝난 스트림도 되감기는 이미 커밋됐을 수 있어
  // 성공 분기가 아니라 여기서 한다. 반면 성공한 턴 뒤의 요약 접기는 서버가 응답 본문을 다 보낸 **뒤에**
  // 백그라운드로 시작하므로, 이 시점의 리페치는 접기 이전 값을 받는다. 열린 패널의 늦은 갱신은 채팅 위젯이
  // 몇 초 뒤 한 번 더 무효화해 메운다. 패널이 닫혀 있으면 리페치 자체가 없고 열 때 다시 받는다.
  void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) });
  // 내 방 목록의 미리보기·최근 활동 순서도 턴이 끝난 뒤에만 갱신한다 — 스트리밍 중에 다시 받으면 답 없는
  // 미리보기만 보인다. 실패로 끝나도 서버가 사용자 메시지를 이미 커밋했을 수 있어 성공 분기가 아니라 여기서 한다.
  void queryClient.invalidateQueries({ queryKey: chatRoomKeys.myLists() });
}
