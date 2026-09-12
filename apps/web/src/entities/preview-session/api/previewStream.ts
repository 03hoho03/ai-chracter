// techspec-builder-common.md §3 — 빌더 미리보기 세션의 SSE 이벤트 스키마·요청 타입. entities/chat-room의
// ChatStreamEvent와 형태는 유사하나 완전히 별도인 데이터 레이어(쿼리 키/상태 타입 분리 — 실제 채팅과 공유하는 것은
// 프레젠테이션 컴포넌트와 `shouldShowSuggestedReplies`뿐이고 엔딩 평가 로직은 가져오지 않는다). 도메인 상태 타입(PreviewStatDef/PreviewShortcut/
// PreviewSessionState)은 `../model/previewSessionState`에 있다.

import { z } from "zod";
import type { components } from "@ai-character-chat/api-types";

export type PreviewStartPayload =
  components["schemas"]["CharacterDraftPayload"] | components["schemas"]["StoryDraftPayload"];

/** SSE `done` 이벤트가 실어 나르므로 스키마에서 도출한다 — 타입을 따로 쓰면 스키마와 갈린다. */
const previewChatMessageSchema = z.object({
  id: z.string(),
  role: z.union([z.literal("user"), z.literal("assistant")]),
  content: z.string(),
  createdAt: z.string(),
});

export type PreviewChatMessage = z.infer<typeof previewChatMessageSchema>;

// BE의 ChatStreamEvent(apps/api/src/api/chat/schemas.py)와 와이어 형태는 동일하지만, entities/chat-room의
// ChatStreamEvent를 import하지 않고 이 레이어 전용으로 별도 선언한다(entities 간 직접 참조 없이 구조적
// 호환만으로 충분 — shared/api/sse의 openChatStream이 이미 이 방식을 쓴다, apps/web/CLAUDE.md 참고).
export const previewStreamEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("token"), delta: z.string() }),
  z.object({ type: z.literal("statChange"), statId: z.string(), newValue: z.number() }),
  z.object({
    type: z.literal("endingReached"),
    endingId: z.string(),
    epilogue: z.string().nullable(),
  }),
  z.object({ type: z.literal("policyWarning"), message: z.string() }),
  z.object({ type: z.literal("done"), finalMessage: previewChatMessageSchema }),
  z.object({ type: z.literal("error"), message: z.string() }),
]);

export type PreviewStreamEvent = z.infer<typeof previewStreamEventSchema>;

// shared/api/sse/openChatStream.ts의 ChatStreamRequestPayload에 구조적으로 맞춘 preview 전용 요청.
export type SendPreviewMessageRequest = {
  kind: "preview-send";
  previewSessionId: string;
  content: string;
  shortcutId: string | null;
};
