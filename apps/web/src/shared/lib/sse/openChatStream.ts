import { apiBaseUrl } from "../api/client";

/** techspec-overview.md §7 — 메시지 전송은 본문이 있는 POST라 네이티브 EventSource(GET 전용)를
 * 쓸 수 없어 fetch + ReadableStream으로 SSE(`data: <json>\n\n`)를 직접 파싱한다. */
export type ChatStreamRequestPayload = {
  roomId: string;
  content: string;
  shortcutId?: string | null;
};

export async function* openChatStream<TEvent>(
  payload: ChatStreamRequestPayload,
): AsyncGenerator<TEvent, void, unknown> {
  const response = await fetch(`${apiBaseUrl}/chat-rooms/${payload.roomId}/messages`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ content: payload.content, shortcutId: payload.shortcutId ?? null }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`SSE request failed with status ${response.status}`);
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += value;

      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex !== -1) {
        const rawEvent = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);

        const data = rawEvent
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice("data:".length).trimStart())
          .join("\n");

        if (data) yield JSON.parse(data) as TEvent;
        separatorIndex = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}
