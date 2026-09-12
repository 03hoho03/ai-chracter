import type { RegenerateRequest } from "../api/chatStream";

export function buildRegeneratePayload(input: { roomId: string }): RegenerateRequest {
  return { kind: "regenerate", roomId: input.roomId };
}
