import type { SendMessageRequest } from "../api/types";

export function buildSendPayload(input: { roomId: string; text: string; shortcutId?: string }): SendMessageRequest {
  return { roomId: input.roomId, content: input.text, shortcutId: input.shortcutId ?? null };
}
