import type { QueryClient } from "@tanstack/react-query";

import { previewSessionKeys } from "../api/keys";
import type { PreviewSessionState, PreviewStreamEvent } from "../api/types";

// entities/chat-room의 applyStreamEvent(techspec-chat-story.md §1.2)와 케이스 구조는 동일하지만
// previewSessionKeys(별도 쿼리 키)만 건드린다 — 실제 대화방 캐시엔 절대 영향을 주지 않는다.
export function applyPreviewStreamEvent(
  queryClient: QueryClient,
  previewSessionId: string,
  event: PreviewStreamEvent,
): void {
  switch (event.type) {
    case "token":
    case "policyWarning":
    case "error":
      return; // Query 캐시 대상 아님 — 스트리밍 버퍼/로컬 에러·경고 상태로만 처리
    case "statChange":
      queryClient.setQueryData<PreviewSessionState>(
        previewSessionKeys.detail(previewSessionId),
        (prev) => prev && { ...prev, stats: { ...prev.stats, [event.statId]: event.newValue } },
      );
      return;
    case "endingReached":
      queryClient.setQueryData<PreviewSessionState>(
        previewSessionKeys.detail(previewSessionId),
        (prev) => prev && { ...prev, endingStatus: { reached: true, epilogue: event.epilogue } },
      );
      return;
    case "done":
      queryClient.setQueryData<PreviewSessionState>(
        previewSessionKeys.detail(previewSessionId),
        (prev) =>
          prev && {
            ...prev,
            messages: [...prev.messages, event.finalMessage],
            turnCount: prev.turnCount + 1,
          },
      );
      return;
  }
}
