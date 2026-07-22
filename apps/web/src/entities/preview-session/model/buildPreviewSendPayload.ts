import type { SendPreviewMessageRequest } from "../api/preview-session";

export function buildPreviewSendPayload(input: {
  previewSessionId: string;
  text: string;
  shortcutId?: string;
}): SendPreviewMessageRequest {
  return {
    kind: "preview-send",
    previewSessionId: input.previewSessionId,
    content: input.text,
    shortcutId: input.shortcutId ?? null,
  };
}
