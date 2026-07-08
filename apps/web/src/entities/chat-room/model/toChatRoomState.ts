import type { components } from "@ai-character-chat/api-types";

import type { ChatRoomState } from "../api/types";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];

// US-055 — apps/api의 ChatRoomResponse(캐릭터 챗, US-051)를 ChatRoomState로 변환하는 유일한 경계.
// 스토리 챗 전용 필드(stats/endingStatus의 실제 값, contentSnapshot 등)는 BE가 아직 보내지 않아
// techspec-chat-character.md §0이 정한 대로 빈 값으로 채운다.
export function toChatRoomState(dto: ChatRoomResponseDto): ChatRoomState {
  return {
    id: dto.id,
    contentId: dto.contentId,
    contentType: dto.contentType,
    name: dto.name,
    messages: dto.messages,
    stats: {},
    endingStatus: { reached: dto.endingReached, endingId: null, reachedAtTurn: null },
    turnCount: dto.turnCount,
    latestVersionAvailable: dto.latestVersionAvailable,
    versionAutoUpgraded: dto.versionAutoUpgraded,
  };
}
