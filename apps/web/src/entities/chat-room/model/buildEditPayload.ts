import type { EditMessageRequest } from "../api/chatStream";

export function buildEditPayload(input: { roomId: string; messageId: string; text: string }): EditMessageRequest {
  return { kind: "edit", roomId: input.roomId, messageId: input.messageId, content: input.text };
}
