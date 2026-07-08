import type { components } from "@ai-character-chat/api-types";

import type {
  ChatMessage,
  ChatRoomState,
  ComparisonOp,
  Ending,
  RuleListItem,
  Shortcut,
  SingleRule,
  StatDef,
} from "../api/types";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];
type ChatMessageDto = ChatRoomResponseDto["messages"][number];
type StatDefSnapshotDto = components["schemas"]["StatDefSnapshot"];
type EndingSnapshotDto = components["schemas"]["EndingSnapshot"];
type EndingRuleItemDto = components["schemas"]["EndingRuleItem"];
type EndingRuleGroupItemDto = components["schemas"]["EndingRuleGroupItem"];

// BE는 DB 컬럼명 그대로의 raw operator(gte/lte/eq/gt/lt, techspec-backend-chat.md의 US-057 노트
// 참고)를 쓰고, entities/chat-room의 provisional 타입(US-052)은 techspec 의사코드의 비교 연산자
// 기호(>=, <= ...)를 쓴다 — 이 매핑이 그 둘의 유일한 경계다.
const OPERATOR_MAP: Record<EndingRuleItemDto["operator"], ComparisonOp> = {
  gte: ">=",
  lte: "<=",
  eq: "==",
  gt: ">",
  lt: "<",
};

function toSingleRule(dto: EndingRuleItemDto): SingleRule {
  return {
    kind: "rule",
    id: dto.id,
    statId: dto.statId,
    operator: OPERATOR_MAP[dto.operator],
    value: dto.threshold,
    nextOp: dto.nextOp,
  };
}

function toRuleListItem(dto: EndingRuleItemDto | EndingRuleGroupItemDto): RuleListItem {
  if (dto.kind === "group") {
    return { kind: "group", id: dto.id, rules: dto.rules.map(toSingleRule), nextOp: dto.nextOp };
  }
  return toSingleRule(dto);
}

function toStatDef(dto: StatDefSnapshotDto): StatDef {
  return {
    id: dto.id,
    name: dto.name,
    icon: dto.icon,
    color: dto.color,
    min: dto.minValue,
    max: dto.maxValue,
    initial: dto.initialValue,
    unit: dto.unit ?? undefined,
    description: dto.description,
  };
}

function toEnding(dto: EndingSnapshotDto): Ending {
  return {
    id: dto.id,
    name: dto.name,
    turnGate: dto.turnCountGate,
    judgePrompt: dto.judgmentPrompt,
    statRules: dto.statRules.map(toRuleListItem),
    epilogue: dto.epilogue ?? undefined,
    endingHint: dto.hint ?? undefined,
  };
}

function toShortcut(dto: components["schemas"]["ShortcutSnapshot"]): Shortcut {
  return { id: dto.id, name: dto.name, description: dto.description, prompt: dto.prompt };
}

function toChatMessage(dto: ChatMessageDto): ChatMessage {
  return {
    id: dto.id,
    role: dto.role,
    content: dto.content,
    imageId: dto.imageId ?? undefined,
    imageUrl: dto.imageUrl ?? undefined,
    createdAt: dto.createdAt,
  };
}

// US-055 — apps/api의 ChatRoomResponse(캐릭터 챗, US-051)를 ChatRoomState로 변환하는 유일한 경계.
// US-060 — 스토리 챗 전용 필드(startingSetupId/stats/contentSnapshot)도 여기서 함께 매핑한다.
// 캐릭터 챗은 BE가 이 필드들을 보내지 않아(null/undefined) techspec-chat-character.md §0이 정한
// 빈 값 그대로 유지된다.
export function toChatRoomState(dto: ChatRoomResponseDto): ChatRoomState {
  return {
    id: dto.id,
    contentId: dto.contentId,
    contentType: dto.contentType,
    name: dto.name,
    startingSetupId: dto.startingSetupId ?? undefined,
    contentSnapshot: dto.contentSnapshot
      ? {
          stats: dto.contentSnapshot.stats.map(toStatDef),
          endings: dto.contentSnapshot.endings.map(toEnding),
          shortcuts: dto.contentSnapshot.shortcuts.map(toShortcut),
          suggestedReplies: dto.contentSnapshot.suggestedReplies,
          pinnedStartingSetupId: dto.contentSnapshot.pinnedStartingSetupId,
        }
      : undefined,
    messages: dto.messages.map(toChatMessage),
    stats: dto.stats ?? {},
    endingStatus: { reached: dto.endingReached, endingId: null, reachedAtTurn: null, epilogue: null },
    turnCount: dto.turnCount,
    latestVersionAvailable: dto.latestVersionAvailable,
    versionAutoUpgraded: dto.versionAutoUpgraded,
  };
}
