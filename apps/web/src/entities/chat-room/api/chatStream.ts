// SSE 이벤트 스키마·요청 타입.
// 도메인 상태 타입(StatDef/Shortcut/Ending/ChatRoomState)은 `../model/chatRoomState`에 있다.

import { z } from "zod";

import { mediaTagImagesSchema } from "@/entities/media-book/@x/chat-room";

/** 장면 헤더의 장면(장소·시간). 모르는 칸은 서버가 null 로 싣고, 앱 안에서는 undefined 로 바꾼다(위 이미지 칸과 같은 정규화). */
const storySceneSchema = z
  .object({ place: z.string().nullable(), time: z.string().nullable() })
  .transform(({ place, time }) => ({ place: place ?? undefined, time: time ?? undefined }));

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
  // 판정 이미지의 픽셀 크기(스토리 미디어 북 그림만 — 캐릭터 상황별 이미지에는 서버가 싣지 않는다). 화면이 그림이
  // 오기 전에 원본 비율로 높이를 잡는 데 쓴다. 없으면 고정 웰이다. 같은 이유로 nullish + 같은 정규화.
  imageWidth: z
    .number()
    .nullish()
    .transform((value) => value ?? undefined)
    .optional(),
  imageHeight: z
    .number()
    .nullish()
    .transform((value) => value ?? undefined)
    .optional(),
  // 장면 헤더를 켠 작품의 AI 응답에 저장된 그 턴의 장면. 꺼진 작품·켜기 전 메시지·사용자 메시지·오프닝은 서버가 null 을 싣는다 —
  // 이미지 칸과 같은 이유로 nullish 로 받고 undefined 로 정규화한다.
  scene: storySceneSchema
    .nullish()
    .transform((value) => value ?? undefined)
    .optional(),
  createdAt: z.string(),
});

/** 메시지 수정·삭제가 지운 턴의 스탯을 어떻게 했는지. `rewound` 는 전부 그 턴 전으로 되돌림, `partial` 은 기록이 없는 옛 턴이
 * 섞여 기록 있는 턴만 되돌림(하나도 못 되돌렸을 수 있다), `kept` 는 되돌리지 않음(중간 답 삭제처럼 정확히 되돌릴 수 없을 때). */
export const statRewindSchema = z.enum(["rewound", "partial", "kept"]);

export type StatRewind = z.infer<typeof statRewindSchema>;

export const chatStreamEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("token"), delta: z.string() }),
  z.object({ type: z.literal("statChange"), statId: z.string(), newValue: z.number() }),
  // 플레이어에게 숨긴 스탯 가운데 신호를 켠 것이 이번 턴에 바뀌었다는 표시 — 인자가 없다(어느 스탯인지·얼마나인지 싣는
  // 순간 숨긴 스탯을 되짚을 수 있다). 한 턴에 많아야 하나이고 `statChange` 들 뒤에 온다. 캐시 변경 없음.
  z.object({ type: z.literal("hiddenStatSignal") }),
  z.object({
    type: z.literal("endingReached"),
    endingId: z.string(),
    epilogue: z.string().nullable(),
    // 에필로그 속 칸 id 형태 태그가 가리키는 그림(`{칸 id: 그림}`).
    mediaTagImages: mediaTagImagesSchema,
  }),
  // 장면 헤더를 켠 작품의 매 턴 장면 — 바뀌지 않았어도 턴마다 `done` 바로 앞에 온다. `messageId` 는 뒤따르는 `done` 의 응답이라
  // 아직 캐시에 없을 수 있다(`applyStreamEvent` 가 들고 있다가 붙인다).
  z.object({
    type: z.literal("sceneChange"),
    messageId: z.string(),
    place: z.string().nullable(),
    time: z.string().nullable(),
  }),
  // 캐시 변경 없음
  z.object({ type: z.literal("policyWarning"), message: z.string() }),
  // `statRewind` 는 지운 턴이 있던 수정의 done 에만 온다. 모르는 값은 버린다 — done 이 튕기면 흐르던 답이 화면에서 사라진다.
  z.object({
    type: z.literal("done"),
    finalMessage: chatMessageSchema,
    statRewind: statRewindSchema.optional().catch(undefined),
  }),
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
