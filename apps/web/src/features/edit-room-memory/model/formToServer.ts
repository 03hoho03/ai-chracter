import type { components } from "@ai-character-chat/api-types";

import type { MemoryFormValues } from "./schema";

type NoteRequest = components["schemas"]["ChatRoomMemoryNoteRequest"];
type SummaryRequest = components["schemas"]["ChatRoomMemorySummaryRequest"];

/** 폼값 → `PUT /chat-rooms/{id}/memory/note`. 요약 칸은 싣지 않는다. */
export function toNoteRequest(values: MemoryFormValues): NoteRequest {
  return { note: values.note };
}

/** 폼값 → `PUT /chat-rooms/{id}/memory/summary`. `version`은 폼을 연 시점(기준값을 굳힌 시점)의 서버
 * 버전이다 — 그사이 요약이 새로 접혔거나 되감겼으면 서버가 409로 거절해 사용자 편집이 새 요약을 조용히
 * 덮지 않는다. */
export function toSummaryRequest(values: MemoryFormValues, version: number): SummaryRequest {
  return { summary: values.summary, version };
}
