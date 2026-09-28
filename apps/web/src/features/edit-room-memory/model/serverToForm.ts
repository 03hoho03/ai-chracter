import type { ChatRoomMemory } from "@/entities/chat-room";

import type { MemoryFormValues } from "./schema";

/** 폼의 기준값. 요약이 아직 없으면(첫 접기 전) 요약 칸은 읽기 전용이라 빈 문자열은 표시용이 아니라 자리만
 * 채운다. */
export function serverToForm(memory: ChatRoomMemory): MemoryFormValues {
  return { note: memory.note, summary: memory.summary?.text ?? "" };
}
