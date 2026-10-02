// StatDef/Shortcut/Ending은 이 스키마를 그대로 반영한다.
// ChatRoomState는 캐릭터/스토리 챗 공용 상태 모델이다.

import type { MediaTagImages } from "@/entities/media-book/@x/chat-room";

import type { ChatMessage } from "../api/chatStream";
import type { RuleListItem } from "./endingRules";

export type { ComparisonOp, LogicOp, RuleGroup, RuleListItem, SingleRule } from "./endingRules";

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

// BE의 실제 ChatRoomResponse(캐릭터 챗)는 storyId가 아니라 contentId를 쓰고
// contentType/name을 함께 내려준다. startingSetupId/contentVersion/contentSnapshot은 스토리 챗
// 전용 필드라 캐릭터 챗에서는 BE가 보내지 않는다 — optional로 두고 캐릭터 챗에서는 그냥 비운다.
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
    pinnedStartingSetupId: string; // 물리적 PK(entity_id인 startingSetupId와 다름). GET /stories/starting-setups/{id}/ending-collection 호출에 쓴다.
  };
  messages: ChatMessage[];
  // 첫 메시지(작성자 글의 복사본)의 칸 id 형태 태그가 가리키는 그림 — 서버가 첫 메시지에 대해서만 준다. 맵에 없는
  // 칸의 태그는 빈칸이다. 필수인 이유: 렌더 때 빈 객체로 채우면 렌더마다 새 맵이 생겨 첫 메시지의 다시 그리기 생략이
  // 깨진다 — 변환(`toChatRoomState`)에서 한 번 채운다.
  openingMediaTagImages: MediaTagImages;
  stats: Record<string, number>; // statId -> 현재값 — 캐릭터 챗에서는 항상 빈 객체
  // `mediaTagImages` 는 에필로그의 칸 id 형태 태그가 가리키는 그림이다(엔딩 도달 이벤트에만 실려 온다).
  endingStatus: {
    reached: boolean;
    endingId?: string;
    reachedAtTurn?: number;
    epilogue?: string;
    mediaTagImages?: MediaTagImages;
  };
  turnCount: number;
  // 방의 대화 프로필. undefined = "선택 안 함"(서버 null). 다음 턴부터 반영된다.
  personaId?: string;
  latestVersionAvailable: boolean; // 원작에 이 방보다 최신 버전이 있는지
  versionAutoUpgraded: boolean; // 이번 조회에서 서버가 자동 마이그레이션했는지
  contentRestricted: boolean; // 작품이 이용제한·삭제돼 이 방에서 대화를 이어갈 수 없는지(읽기·삭제·초기화는 된다)
};
