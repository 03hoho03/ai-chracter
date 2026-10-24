import type { components } from "@ai-character-chat/api-types";

import type { ChatRoomMemoryItemsPage } from "../model/chatRoomMemoryItems";

type ChatRoomMemoryItemsDto = components["schemas"]["ChatRoomMemoryItemsResponse"];

/** 목록 API 한 페이지를 화면 모양으로 바꾼다. 서버의 null은 여기서 없는 값으로 바꾼다. */
export function toChatRoomMemoryItemsPage(dto: ChatRoomMemoryItemsDto): ChatRoomMemoryItemsPage {
  return {
    episodes: dto.episodes.map((episode) => ({
      id: episode.id,
      title: episode.title,
      detail: episode.detail,
      assertedBy: episode.assertedBy,
      startTurn: episode.startTurn,
      endTurn: episode.endTurn,
    })),
    nextCursor: dto.nextCursor ?? undefined,
    facts: dto.facts.map((fact) => ({
      id: fact.id,
      factKey: fact.factKey,
      kind: fact.kind,
      subject: fact.subject,
      object: fact.object ?? undefined,
      attribute: fact.attribute ?? undefined,
      value: fact.value,
      truthStatus: fact.truthStatus,
      truthLabel: fact.truthLabel,
      assertedBy: fact.assertedBy,
      speaker: fact.speaker ?? undefined,
      startTurn: fact.startTurn,
      endTurn: fact.endTurn,
    })),
    episodesUsedInReplies: dto.episodesUsedInReplies,
    factsUsedInReplies: dto.factsUsedInReplies,
  };
}
