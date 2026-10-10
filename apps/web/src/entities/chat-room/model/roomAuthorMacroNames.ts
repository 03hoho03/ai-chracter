import { resolveAuthorMacroNames, type AuthorMacroNames } from "@/shared/lib/text/authorMacros";

import type { ChatRoomState } from "./chatRoomState";

/** 방 화면(메시지·칩·단축어·스탯·엔딩, 방에서 연 모달)과 보내기 전 치환이 함께 쓰는 이름 — 방의 프로필 이름이 먼저다. */
export function roomAuthorMacroNames(
  room: Pick<ChatRoomState, "contentType" | "personaName" | "contentName">,
): AuthorMacroNames {
  return resolveAuthorMacroNames({
    personaName: room.personaName,
    contentType: room.contentType,
    contentName: room.contentName,
  });
}
