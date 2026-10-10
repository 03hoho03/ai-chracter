import type { components } from "@ai-character-chat/api-types";

import { DEFAULT_CHAT_MODEL } from "@/entities/chat-model/@x/chat-room";
import { toMediaTagImages } from "@/entities/media-book/@x/chat-room";

import type { ChatMessage } from "./chatStream";
import type {
  ChatRoomState,
  ComparisonOp,
  Ending,
  RuleListItem,
  Shortcut,
  SingleRule,
  StatDef,
} from "../model/chatRoomState";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];
type ChatMessageDto = ChatRoomResponseDto["messages"][number];
type StatDefSnapshotDto = components["schemas"]["StatDefSnapshot"];
type EndingSnapshotDto = components["schemas"]["EndingSnapshot"];
type EndingRuleItemDto = components["schemas"]["EndingRuleItem"];
type EndingRuleGroupItemDto = components["schemas"]["EndingRuleGroupItem"];

// BE는 DB 컬럼명 그대로의 raw operator(gte/lte/eq/gt/lt)를
// 쓰고, entities/chat-room의 provisional 타입은 비교 연산자
// 기호(>=, <= ...)를 쓴다 — 이 매핑이 그 둘의 유일한 경계다. 작성 가이드의 엔딩 규칙 예시도 시드(서버 표기) 값을 이
// 매핑으로 빌더 화면의 기호로 바꿔 그린다.
export const OPERATOR_MAP: Record<EndingRuleItemDto["operator"], ComparisonOp> = {
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

export function toChatMessage(dto: ChatMessageDto): ChatMessage {
  return {
    id: dto.id,
    role: dto.role,
    content: dto.content,
    imageId: dto.imageId ?? undefined,
    imageUrl: dto.imageUrl ?? undefined,
    imageWidth: dto.imageWidth ?? undefined,
    imageHeight: dto.imageHeight ?? undefined,
    createdAt: dto.createdAt,
  };
}

// apps/api의 ChatRoomResponse(캐릭터 챗)를 ChatRoomState로 변환하는 유일한 경계.
// 스토리 챗 전용 필드(startingSetupId/stats/contentSnapshot)도 여기서 함께 매핑한다.
// 캐릭터 챗은 BE가 이 필드들을 보내지 않아(null/undefined)
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
    hasMoreMessagesBefore: dto.hasMoreMessagesBefore,
    openingMediaTagImages: toMediaTagImages(dto.mediaTagImages),
    stats: dto.stats ?? {},
    // 도달한 엔딩은 스트림 이벤트처럼 방 응답에도 실려 와, 방을 다시 받아도 에필로그가 남는다. 이 칸이 없는 옛 서버
    // 응답(또는 null)은 도달 여부만 옮긴다. 도달 턴 번호는 방 응답에 없다.
    endingStatus: dto.ending
      ? {
          reached: dto.endingReached,
          endingId: dto.ending.endingId,
          reachedAtTurn: undefined,
          epilogue: dto.ending.epilogue ?? undefined,
          mediaTagImages: toMediaTagImages(dto.ending.mediaTagImages),
        }
      : { reached: dto.endingReached, endingId: undefined, reachedAtTurn: undefined, epilogue: undefined },
    turnCount: dto.turnCount,
    personaId: dto.personaId ?? undefined,
    personaName: dto.personaName ?? undefined,
    contentName: dto.contentName,
    latestVersionAvailable: dto.latestVersionAvailable,
    versionAutoUpgraded: dto.versionAutoUpgraded,
    contentRestricted: dto.contentRestricted,
    // 이 칸이 생기기 전의 서버 응답에는 없다. 그 서버는 막지도 않으므로 "막지 않음"으로 읽는다 — 반대로 읽으면 모든 방에서
    // 「소설로 보기」가 막힌다.
    novelCreationBlocked: dto.novelCreationBlocked ?? false,
    // 두 칸은 응답 스키마상 선택이다(서버 기본값이 있는 칸). 모델은 서버 기본값과 같은 기본 모델로 채우고, 가격은
    // 화면이 사본을 두지 않도록 비워 둔다.
    effectiveChatModel: dto.effectiveChatModel ?? DEFAULT_CHAT_MODEL,
    // 이름은 기본 모델 이름으로 채우지 않는다 — 모델 칸이 없어 기본 모델로 읽은 방이 실제로는 상위 모델 방일 수 있다.
    effectiveChatModelName: dto.effectiveChatModelName,
    turnCost: dto.turnCost,
  };
}
