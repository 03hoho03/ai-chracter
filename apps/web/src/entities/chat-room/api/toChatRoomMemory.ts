import type { components } from "@ai-character-chat/api-types";

import type { ChatRoomMemory } from "../model/chatRoomMemory";

type ChatRoomMemoryDto = components["schemas"]["ChatRoomMemoryResponse"];

// 기억 조회와 기억 쓰기 네 경로가 같은 응답을 준다 — 어느 쪽으로 받든 이 변환 하나를 거쳐 캐시에 같은
// 모양으로 들어간다. 서버의 null은 여기서 undefined로 바꾼다.
export function toChatRoomMemory(dto: ChatRoomMemoryDto): ChatRoomMemory {
  return {
    note: dto.note,
    summary: dto.summary
      ? {
          text: dto.summary.text,
          source: dto.summary.source,
          canRevert: dto.summary.canRevert,
          updatedAt: dto.summary.updatedAt,
        }
      : undefined,
    version: dto.version,
    rolledBackAt: dto.rolledBackAt ?? undefined,
    limits: { noteMaxLength: dto.limits.noteMaxLength, summaryMaxLength: dto.limits.summaryMaxLength },
  };
}
