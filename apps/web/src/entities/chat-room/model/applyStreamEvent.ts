import type { QueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "../api/keys";
import type { ChatMessage, ChatRoomState, ChatStreamEvent } from "../api/chat-room";

type ApplyStreamEventOptions = {
  mode?: "append" | "replaceLast"; // 기본 append, 재생성 시 replaceLast(techspec-chat-common.md §2.1)
  onDone?: (message: ChatMessage, prev: ChatRoomState) => void; // 'done' 처리 직후 호출되는 확장 훅(예: 이미지 보관함 invalidate)
};

// techspec-chat-story.md §1.2 — 이 파일이 SSE 이벤트를 TanStack Query 캐시에 반영하는 유일한 경계다.
// 캐시 shape을 아는 코드는 여기뿐이어야 하며, 호출부는 이벤트를 전달만 한다.
export function applyStreamEvent(
  queryClient: QueryClient,
  roomId: string,
  event: ChatStreamEvent,
  opts: ApplyStreamEventOptions = {},
): void {
  const mode = opts.mode ?? "append";

  switch (event.type) {
    case "token":
    case "policyWarning":
    case "error":
      return; // Query 캐시 대상 아님 — 스트리밍 버퍼/로컬 에러·경고 상태로만 처리(오버뷰 §5)
    case "statChange":
      queryClient.setQueryData<ChatRoomState>(
        chatRoomKeys.detail(roomId),
        (prev) => prev && { ...prev, stats: { ...prev.stats, [event.statId]: event.newValue } },
      );
      return;
    case "endingReached":
      queryClient.setQueryData<ChatRoomState>(
        chatRoomKeys.detail(roomId),
        (prev) =>
          prev && {
            ...prev,
            endingStatus: {
              reached: true,
              endingId: event.endingId,
              reachedAtTurn: prev.turnCount,
              epilogue: event.epilogue,
            },
          },
      );
      return;
    case "done":
      queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), (prev) => {
        if (!prev) return prev;
        const messages =
          mode === "replaceLast"
            ? [...prev.messages.slice(0, -1), event.finalMessage]
            : [...prev.messages, event.finalMessage];
        const next: ChatRoomState = { ...prev, messages, turnCount: prev.turnCount + 1 };
        opts.onDone?.(event.finalMessage, prev);
        return next;
      });
      return;
  }
}
