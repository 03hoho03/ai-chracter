import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "@/entities/chat-room";

import { createMemoryFollowUpRefresher, type MemoryFollowUpState } from "../model/memoryFollowUpRefresh";

/** 기억 패널이 열린 채 전송이 끝나면 잠시 뒤 기억을 한 번 더 받는다(규칙은 `createMemoryFollowUpRefresher`).
 * 스트림이 끝날 때의 무효화(`useSendMessage`)는 서버가 요약을 접기 전에 일어나므로 그것만으로는 열린 패널이
 * 접기 결과를 다음 턴까지 못 본다. */
export function useMemoryFollowUpRefresh(state: MemoryFollowUpState): void {
  const queryClient = useQueryClient();
  const [refresher] = useState(() =>
    createMemoryFollowUpRefresher((roomId) => {
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) });
    }),
  );
  const { roomId, isSending, isPanelOpen } = state;

  useEffect(() => {
    refresher.update({ roomId, isSending, isPanelOpen });
  }, [refresher, roomId, isSending, isPanelOpen]);

  useEffect(() => () => refresher.dispose(), [refresher]);
}
