import type { RegenerateRequest } from "../api/chat-room";

export function buildRegeneratePayload(input: { roomId: string }): RegenerateRequest {
  return { kind: "regenerate", roomId: input.roomId };
}
