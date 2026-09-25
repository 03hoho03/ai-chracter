import type { ZodType } from "zod";

import { assertNever } from "@/shared/lib/assertNever";

import { API_BASE_URL, ApiErrorObject, errorEnvelopeSchema } from "../client";

/** 메시지 전송/재생성/수정은 모두 본문이 있는 POST/PATCH라 네이티브
 * EventSource(GET 전용)를 쓸 수 없어 fetch + ReadableStream으로 SSE(`data: <json>\n\n`)를
 * 직접 파싱한다. kind로 각 엔드포인트(전송/재생성/수정 / 미리보기 전송)의
 * 메서드·URL·바디를 분기한다. */
export type ChatStreamRequestPayload =
  | { kind: "send"; roomId: string; content: string; shortcutId?: string | null }
  | { kind: "regenerate"; roomId: string }
  | { kind: "edit"; roomId: string; messageId: string; content: string }
  | { kind: "preview-send"; previewSessionId: string; content: string; shortcutId?: string | null };

function buildRequestInit(payload: ChatStreamRequestPayload): { url: string; init: RequestInit } {
  const headers = { "Content-Type": "application/json", Accept: "text/event-stream" };

  switch (payload.kind) {
    case "send":
      return {
        url: `${API_BASE_URL}/chat-rooms/${payload.roomId}/messages`,
        init: {
          method: "POST",
          headers,
          body: JSON.stringify({ content: payload.content, shortcutId: payload.shortcutId ?? null }),
        },
      };
    case "regenerate":
      return { url: `${API_BASE_URL}/chat-rooms/${payload.roomId}/regenerate`, init: { method: "POST", headers } };
    case "edit":
      return {
        url: `${API_BASE_URL}/chat-rooms/${payload.roomId}/messages/${payload.messageId}`,
        init: { method: "PATCH", headers, body: JSON.stringify({ content: payload.content }) },
      };
    case "preview-send":
      return {
        url: `${API_BASE_URL}/preview-sessions/${payload.previewSessionId}/messages`,
        init: {
          method: "POST",
          headers,
          body: JSON.stringify({ content: payload.content, shortcutId: payload.shortcutId ?? null }),
        },
      };
    default:
      return assertNever(payload);
  }
}

/**
 * 실패 응답의 **바디를 읽어** `ApiErrorObject`로 던진다. 이 경로는
 * fetch라 `apiClient`의 응답 인터셉터를 타지 않아서, 여기서 읽지 않으면 429의 `retryAfterSeconds`도
 * 403 재동의의 `code`도 소비처에 영원히 닿지 않는다(둘 다 detail 안에만 있고 헤더에는 없다 —
 * BE가 `Retry-After`를 일부러 주지 않는다: CORS 응답에서 브라우저가 못 읽는다).
 *
 * 파싱에 실패해도(프록시가 끼워 넣은 HTML 502 등) **던지기는 한다** — detail만 undefined인 같은
 * 모양이다. 파싱 실패가 스트림을 조용히 성공시키면 화면은 응답을 영원히 기다린다.
 * 422 검증 배열은 여기서 버린다(`client.ts`의 `normalizeError`는 `fields`로 펼치지만, SSE 경로에
 * 필드 에러를 읽는 소비처가 없다).
 */
async function toApiError(response: Response): Promise<ApiErrorObject> {
  const parsed = await response.json().then(
    (body: unknown) => errorEnvelopeSchema.safeParse(body),
    () => null,
  );
  const detail = parsed?.success === true ? parsed.data.detail : undefined;

  return new ApiErrorObject({
    status: response.status,
    detail: Array.isArray(detail) ? undefined : detail,
    message: `SSE request failed with status ${response.status}`,
  });
}

/**
 * SSE 스트림을 이벤트 단위로 흘려보낸다.
 *
 * `eventSchema`를 받는 이유: `JSON.parse`는 `any`를 돌려주고, 이전엔 그걸 `as TEvent`로
 * 단언했다 — 서버가 모양을 바꾸거나 알 수 없는 이벤트를 보내면 그 거짓말이 그대로 소비처까지
 * 흘러가 `event.type` 스위치의 default에서야(운 좋으면) 걸렸다. 이제 파싱에 실패한 이벤트는
 * **그 줄만 건너뛰고** 스트림은 계속된다 — 토큰 하나가 이상하다고 대화 전체를 죽이지 않는다.
 */
export async function* openChatStream<TEvent>(
  payload: ChatStreamRequestPayload,
  eventSchema: ZodType<TEvent>,
): AsyncGenerator<TEvent, void, unknown> {
  const { url, init } = buildRequestInit(payload);
  const response = await fetch(url, { ...init, credentials: "include" });

  // 바디 파싱은 `!response.ok`에만 건다 — 200인데 body가 없는 경우엔 읽을 에러 봉투가 없다.
  if (!response.ok) throw await toApiError(response);
  if (!response.body) {
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

        if (data) {
          const parsed = eventSchema.safeParse(JSON.parse(data));
          // 모르는 이벤트는 조용히 흘리지 않고 남긴다 — 서버가 새 타입을 보내기 시작했는데
          // 화면이 무반응이면 원인을 찾을 단서가 이것뿐이다.
          if (parsed.success) yield parsed.data;
          else console.warn("[sse] 알 수 없는 이벤트를 건너뛴다", parsed.error.issues);
        }
        separatorIndex = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}
