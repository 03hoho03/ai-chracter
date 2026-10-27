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
    // 칸이 아예 없는 응답(이 칸을 싣기 전의 서버)도 null 과 같이 구획을 그리지 않는다.
    impressions: dto.impressions?.map((impression) => ({
      id: impression.id,
      text: impression.text,
      createdAt: impression.createdAt,
      turnStart: impression.turnStart ?? undefined,
      turnEnd: impression.turnEnd ?? undefined,
      sceneCount: impression.sceneCount,
      factCount: impression.factCount,
    })),
  };
}
