import { apiBaseUrl } from "../api/client";

/** techspec-overview.md §7 — 메시지 전송/재생성/수정은 모두 본문이 있는 POST/PATCH라 네이티브
 * EventSource(GET 전용)를 쓸 수 없어 fetch + ReadableStream으로 SSE(`data: <json>\n\n`)를
 * 직접 파싱한다. kind로 세 엔드포인트(전송/재생성/수정, US-077)의 메서드·URL·바디를 분기한다. */
export type ChatStreamRequestPayload =
  | { kind: "send"; roomId: string; content: string; shortcutId?: string | null }
  | { kind: "regenerate"; roomId: string }
  | { kind: "edit"; roomId: string; messageId: string; content: string };

function buildRequestInit(payload: ChatStreamRequestPayload): { url: string; init: RequestInit } {
  const headers = { "Content-Type": "application/json", Accept: "text/event-stream" };

  switch (payload.kind) {
    case "send":
      return {
        url: `${apiBaseUrl}/chat-rooms/${payload.roomId}/messages`,
        init: {
          method: "POST",
          headers,
          body: JSON.stringify({ content: payload.content, shortcutId: payload.shortcutId ?? null }),
        },
      };
    case "regenerate":
      return { url: `${apiBaseUrl}/chat-rooms/${payload.roomId}/regenerate`, init: { method: "POST", headers } };
    case "edit":
      return {
        url: `${apiBaseUrl}/chat-rooms/${payload.roomId}/messages/${payload.messageId}`,
        init: { method: "PATCH", headers, body: JSON.stringify({ content: payload.content }) },
      };
  }
}

export async function* openChatStream<TEvent>(
  payload: ChatStreamRequestPayload,
): AsyncGenerator<TEvent, void, unknown> {
  const { url, init } = buildRequestInit(payload);
  const response = await fetch(url, { ...init, credentials: "include" });

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
