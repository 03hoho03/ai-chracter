import type { RegenerateRequest } from "../api/types";

export function buildRegeneratePayload(input: { roomId: string }): RegenerateRequest {
  return { kind: "regenerate", roomId: input.roomId };
}
