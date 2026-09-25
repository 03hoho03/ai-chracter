// SSE 이벤트 스키마·요청 타입.
// 도메인 상태 타입(StatDef/Shortcut/Ending/ChatRoomState)은 `../model/chatRoomState`에 있다.

import { z } from "zod";

/** SSE 이벤트는 **스키마가 단일 소스**다 — 타입을 따로 쓰고 스키마를 덧붙이면 둘이 갈린다
 * `openChatStream`이 이 스키마로 파싱하므로 서버가 모양을 바꾸면
 * 소비처가 아니라 여기서 걸린다. */
const chatMessageSchema = z.object({
  id: z.string(),
  role: z.union([z.literal("user"), z.literal("assistant")]),
  content: z.string(),
  // 상황별 이미지 매칭 결과(캐릭터 챗 전용). **`.nullish()`여야 한다** — 매칭이 없을 때 서버는
  // 키를 빼는 게 아니라 `null`을 실어 보낸다(`ChatMessageResponse.image_id`의 기본값이 `None`이고
  // pydantic이 그대로 직렬화한다). `.optional()`이면 `done` 이벤트가 통째로 파싱에 실패해
  // **답변이 화면에 찍히다가 사라진다** — token은 통과해 글자가 흐르는데 done이 튕겨
  // finalMessage가 커밋되지 않고 스트리밍 버퍼만 비워지기 때문이다(2026-09-02 프로덕션 실측).
  // `packages/api-types`의 codegen은 처음부터 `imageId?: string | null`이라고 적고 있었다.
  // 출력은 `null`을 `undefined`로 정규화한다(앱 내부 타입에 null을 흘리지
  // 않는다). 재조회 경로 `toChatMessage`의 `?? undefined`와 같은 값이 되어 SSE로 온 메시지와
  // GET으로 온 메시지의 필드 모양이 갈리지 않는다. 앞의 `.nullish()`가 입력의 `null`을 그대로
  // 통과시키므로 위 경고와 충돌하지 않고, 끝의 `.optional()`은 출력 키를 옵셔널로 유지하기 위한
  // 것이다(`.transform`만 붙이면 `imageId: string | undefined` 필수 키가 된다 — zod 4.4.3 실측).
  imageId: z
    .string()
    .nullish()
    .transform((value) => value ?? undefined)
    .optional(),
  // imageId와 함께 채워지는 presigned GET URL(인라인 렌더링용 — 재조회 응답에도 실린다, BE
  // `ChatMessageResponse.image_url` 주석 참조). 같은 이유로 nullish + 같은 정규화.
  imageUrl: z
    .string()
    .nullish()
    .transform((value) => value ?? undefined)
    .optional(),
  createdAt: z.string(),
});

export const chatStreamEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("token"), delta: z.string() }),
  z.object({ type: z.literal("statChange"), statId: z.string(), newValue: z.number() }),
  z.object({
    type: z.literal("endingReached"),
    endingId: z.string(),
    epilogue: z.string().nullable(),
  }),
  // 캐시 변경 없음
  z.object({ type: z.literal("policyWarning"), message: z.string() }),
  z.object({ type: z.literal("done"), finalMessage: chatMessageSchema }),
  // 캐시 변경 없음
  z.object({ type: z.literal("error"), message: z.string() }),
]);

export type ChatStreamEvent = z.infer<typeof chatStreamEventSchema>;

/** SSE `done` 이벤트가 실어 나르므로 스키마에서 도출한다 — 타입을 따로 쓰면 스키마와 갈린다. */
export type ChatMessage = z.infer<typeof chatMessageSchema>;

// SSE 이벤트 스키마 [확정] — BE가 이 스키마를 그대로 채택


export type SendMessageRequest = {
  kind: "send";
  roomId: string;
  content: string;
  shortcutId: string | null;
};

// 재생성/수정도 send와 동일하게 SSE로 열리므로, openChatStream이 메서드/URL/바디를
// 분기할 수 있도록 kind로 식별되는 요청 셋을 이룬다.
export type RegenerateRequest = { kind: "regenerate"; roomId: string };

export type EditMessageRequest = { kind: "edit"; roomId: string; messageId: string; content: string };

export type ChatStreamRequest = SendMessageRequest | RegenerateRequest | EditMessageRequest;
