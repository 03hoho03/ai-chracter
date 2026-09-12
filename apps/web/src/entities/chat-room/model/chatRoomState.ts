// techspec-builder-story.md §1.2/§1.4/§1.5 — StatDef/Shortcut/Ending은 이 스키마를 그대로 반영한다.
// techspec-chat-story.md §1.1/§1.2, techspec-content-versioning.md §2 — ChatRoomState는 캐릭터/스토리
// 챗 공용 상태 모델이다.

import type { RuleListItem } from "@/shared/lib/rule-engine/endingRules";

import type { ChatMessage } from "../api/chatStream";

export type { ComparisonOp, LogicOp, RuleGroup, RuleListItem, SingleRule } from "@/shared/lib/rule-engine/endingRules";

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
  endingStatus: { reached: boolean; endingId?: string; reachedAtTurn?: number; epilogue?: string };
  turnCount: number;
  latestVersionAvailable: boolean; // 원작에 이 방보다 최신 버전이 있는지
  versionAutoUpgraded: boolean; // 이번 조회에서 서버가 자동 마이그레이션했는지
};
