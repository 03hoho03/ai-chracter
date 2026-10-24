import { useMemo } from "react";

import { useChatRoomSourceMessagesQuery } from "@/entities/chat-room";
import type { NovelDetailResponse } from "@/entities/novel";
import type { OutlineTurn } from "@/features/plan-novel-outline";
import { buildSourceTurns } from "@/features/select-novel-source";

/** 구성 화면들이 근거 턴 번호를 세는 턴 — 담을 대화 단계와 같은 묶기(같은 대화방 메시지 캐시)라 세 단계의 턴 번호가 같다. 두 기능을
 * 이 위젯이 잇는다(기능끼리 가져다 쓰지 않는다). 방이 지워진 소설은 대화를 읽지 않는다. */
export function usePlanTurns(novel: Pick<NovelDetailResponse, "chatRoomId">): {
  turns: readonly OutlineTurn[] | undefined;
  isTurnsFailed: boolean;
} {
  const messagesQuery = useChatRoomSourceMessagesQuery(novel.chatRoomId, { enabled: novel.chatRoomId !== null });
  const messages = messagesQuery.data;
  const turns = useMemo(
    () =>
      messages === undefined
        ? undefined
        : buildSourceTurns(messages, { fixedEndId: null, roomEndId: messages.at(-1)?.id ?? null, lockedRanges: [] }),
    [messages],
  );
  return { turns, isTurnsFailed: messagesQuery.isError && messages === undefined };
}
