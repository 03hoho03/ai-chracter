// techspec-chat-story.md §1.1/§1.2, techspec-content-versioning.md §2 — 캐릭터/스토리 챗 공용 상태 모델.
// StatDef/Shortcut/Ending은 techspec-builder-story.md §1.2/§1.4/§1.5의 스키마를 그대로 반영한다.

import type { RuleListItem } from "../../../shared/lib/rule-engine/types";

export type { ComparisonOp, LogicOp, RuleGroup, RuleListItem, SingleRule } from "../../../shared/lib/rule-engine/types";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  imageId?: string; // 상황별 이미지 매칭 결과(캐릭터 챗 전용) — 스토리 챗에서는 항상 undefined
  imageUrl?: string; // imageId와 함께 채워지는 presigned GET URL(인라인 렌더링용, 세션 한정)
  createdAt: string;
};

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
export type ChatStreamEvent =
  | { type: "token"; delta: string }
  | { type: "statChange"; statId: string; newValue: number }
  | { type: "endingReached"; endingId: string; epilogue: string | null }
  | { type: "policyWarning"; message: string } // 캐시 변경 없음(techspec-chat-common.md §5)
  | { type: "done"; finalMessage: ChatMessage }
  | { type: "error"; message: string }; // 캐시 변경 없음(techspec-chat-common.md §1)

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
