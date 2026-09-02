// techspec-chat-story.md §1.1/§1.2, techspec-content-versioning.md §2 — 캐릭터/스토리 챗 공용 상태 모델.
// StatDef/Shortcut/Ending은 techspec-builder-story.md §1.2/§1.4/§1.5의 스키마를 그대로 반영한다.

import { z } from "zod";
import type { RuleListItem } from "@/shared/lib/rule-engine/ending-rules";

export type { ComparisonOp, LogicOp, RuleGroup, RuleListItem, SingleRule } from "@/shared/lib/rule-engine/ending-rules";

/** SSE 이벤트는 **스키마가 단일 소스**다 — 타입을 따로 쓰고 스키마를 덧붙이면 둘이 갈린다
 * (fe-typescript TS-09). `openChatStream`이 이 스키마로 파싱하므로 서버가 모양을 바꾸면
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
  imageId: z.string().nullish(),
  // imageId와 함께 채워지는 presigned GET URL(인라인 렌더링용, 세션 한정). 같은 이유로 nullish.
  imageUrl: z.string().nullish(),
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
  // 캐시 변경 없음(techspec-chat-common.md §5)
  z.object({ type: z.literal("policyWarning"), message: z.string() }),
  z.object({ type: z.literal("done"), finalMessage: chatMessageSchema }),
  // 캐시 변경 없음(techspec-chat-common.md §1)
  z.object({ type: z.literal("error"), message: z.string() }),
]);

export type ChatStreamEvent = z.infer<typeof chatStreamEventSchema>;

/** SSE `done` 이벤트가 실어 나르므로 스키마에서 도출한다 — 타입을 따로 쓰면 스키마와 갈린다. */
export type ChatMessage = z.infer<typeof chatMessageSchema>;

export type StatDef = {
  id: string;
  name: string;
  icon: string;
  color: string;
  min: number;
  max: number;
  initial: number;
  unit?: string;
  description: string;
};

export type Shortcut = {
  id: string;
  name: string;
  description: string;
  prompt: string;
};

export type Ending = {
  id: string;
  name: string;
  turnGate: number;
  judgePrompt: string;
  statRules: RuleListItem[]; // 비어있으면 judgePrompt만으로 판정
  epilogue?: string;
  endingHint?: string;
};

// US-055 — BE의 실제 ChatRoomResponse(캐릭터 챗, US-051)는 storyId가 아니라 contentId를 쓰고
// contentType/name을 함께 내려준다. startingSetupId/contentVersion/contentSnapshot은 스토리 챗
// 전용 필드라 아직 BE가 보내지 않는다(US-057 이전) — optional로 두고 캐릭터 챗에서는 그냥 비운다.
export type ChatRoomState = {
  id: string;
  contentId: string;
  contentType: "character" | "story";
  name: string;
  startingSetupId?: string;
  contentVersion?: number; // 고정된 콘텐츠 버전
  contentSnapshot?: {
    stats: StatDef[];
    endings: Ending[];
    shortcuts: Shortcut[];
    suggestedReplies: string[];
    pinnedStartingSetupId: string; // US-070 — 물리적 PK(entity_id인 startingSetupId와 다름). GET /stories/starting-setups/{id}/ending-collection 호출에 쓴다.
  };
  messages: ChatMessage[];
  stats: Record<string, number>; // statId -> 현재값 — 캐릭터 챗에서는 항상 빈 객체(techspec-chat-character.md §0)
  endingStatus: { reached: boolean; endingId: string | null; reachedAtTurn: number | null; epilogue: string | null };
  turnCount: number;
  latestVersionAvailable: boolean; // 원작에 이 방보다 최신 버전이 있는지
  versionAutoUpgraded: boolean; // 이번 조회에서 서버가 자동 마이그레이션했는지
};

// SSE 이벤트 스키마 [확정] — BE가 이 스키마를 그대로 채택(techspec-overview-backend.md §3)


export type SendMessageRequest = {
  kind: "send";
  roomId: string;
  content: string;
  shortcutId: string | null;
};

// US-077 — 재생성/수정도 send와 동일하게 SSE로 열리므로, openChatStream이 메서드/URL/바디를
// 분기할 수 있도록 kind로 식별되는 요청 셋을 이룬다(techspec-chat-common.md §2.1).
export type RegenerateRequest = { kind: "regenerate"; roomId: string };

export type EditMessageRequest = { kind: "edit"; roomId: string; messageId: string; content: string };

export type ChatStreamRequest = SendMessageRequest | RegenerateRequest | EditMessageRequest;
