import type { QueryClient } from "@tanstack/react-query";

import { assertNever } from "@/shared/lib/assertNever";

import { chatRoomKeys } from "../api/keys";
import type { ChatMessage, ChatStreamEvent } from "../api/chatStream";
import type { ChatRoomState } from "./chatRoomState";

type ApplyStreamEventOptions = {
  // 기본은 새 턴(전송·편집). 재생성은 turnCount를 올리지
  // 않고(서버도 안 올린다, chat/router.py:1121) done이 꼬리 assistant를 걷어낸다.
  kind?: "newTurn" | "regenerate";
  onDone?: (message: ChatMessage, prev: ChatRoomState) => void; // 'done' 처리 직후 호출되는 확장 훅(예: 이미지 보관함 invalidate)
};

// 이 파일이 SSE 이벤트를 TanStack Query 캐시에 반영하는 유일한 경계다 — 호출부는 이벤트를 전달만 한다.
// 낙관적 조작(사용자 메시지 추가·편집 절단·재생성 제거)은 이 경계 밖이고, `apps/web/CLAUDE.md`의
// "캐시 조작은 QueryClient를 인자로 받는 순수 함수" 규칙대로 truncateAndEdit·dropLastMessage가 맡는다.
export function applyStreamEvent(
  queryClient: QueryClient,
  roomId: string,
  event: ChatStreamEvent,
  opts: ApplyStreamEventOptions = {},
): void {
  const kind = opts.kind ?? "newTurn";

  switch (event.type) {
    case "token":
    case "policyWarning":
    case "error":
      return; // Query 캐시 대상 아님 — 스트리밍 버퍼/로컬 에러·경고 상태로만 처리
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
              epilogue: event.epilogue ?? undefined,
            },
          },
      );
      return;
    case "done":
      queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), (prev) => {
        if (!prev) return prev;
        // 재생성에서만 꼬리 assistant를 걷어낸다. 정상 경로는 낙관적 제거로 꼬리가
        // user라 무발동이고, 탭 복귀 재조회가 옛 답변을 되살린 경우에만 발동한다. 전송·편집에는
        // 걸지 않는다 — 그쪽에서 꼬리가 assistant라는 건 직전 턴의 답변이라는 뜻이다.
        const tail = prev.messages.at(-1);
        const base =
          kind === "regenerate" && tail?.role === "assistant" ? prev.messages.slice(0, -1) : prev.messages;
        const next: ChatRoomState = {
          ...prev,
          messages: [...base, event.finalMessage],
          turnCount: kind === "newTurn" ? prev.turnCount + 1 : prev.turnCount,
        };
        opts.onDone?.(event.finalMessage, prev);
        return next;
      });
      return;
    default:
      return assertNever(event);
  }
}
