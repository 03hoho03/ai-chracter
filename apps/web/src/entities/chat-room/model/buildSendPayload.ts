import type { SendMessageRequest } from "../api/chat-room";

export function buildSendPayload(input: { roomId: string; text: string; shortcutId?: string }): SendMessageRequest {
  return { kind: "send", roomId: input.roomId, content: input.text, shortcutId: input.shortcutId ?? null };
}
