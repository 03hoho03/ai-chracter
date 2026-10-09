// StatDef/Shortcut/Ending은 이 스키마를 그대로 반영한다.
// ChatRoomState는 캐릭터/스토리 챗 공용 상태 모델이다.

import type { ChatModelId } from "@/entities/chat-model/@x/chat-room";
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
  // 긴 방은 최근 메시지만 받고 위로 올라갈 때 앞을 이어 받는다 — `messages` 앞에 서버에 메시지가 더 있는가.
  // 참이면 `messages[0]` 은 방의 첫 메시지(작성자 글)가 아니다.
  hasMoreMessagesBefore: boolean;
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
  // 작가 글의 `{{user}}`·`{{char}}` 를 화면에서 바꿀 때 쓰는 이름들(`roomAuthorMacroNames`). 모두 방이 고정한 버전
  // 기준이다 — 화면의 작품 상세는 최신 발행본이라 그것으로 대신하면 모델이 부른 이름과 갈릴 수 있다.
  personaName?: string; // 방 프로필의 이름. undefined = 프로필 없음
  defaultUserName: string; // 작가가 정한 작품 기본 이름. 빈 값이면 대체어
  contentName?: string; // 작품 이름 — 캐릭터 작품에서 `{{char}}` 가 된다
  latestVersionAvailable: boolean; // 원작에 이 방보다 최신 버전이 있는지
  versionAutoUpgraded: boolean; // 이번 조회에서 서버가 자동 마이그레이션했는지
  contentRestricted: boolean; // 작품이 이용제한·삭제돼 이 방에서 대화를 이어갈 수 없는지(읽기·삭제·초기화는 된다)
  // 이 방에서 새 소설을 만들 수 없는지 — 원작자가 소설 만들기를 허용하지 않았고, 내가 작가가 아니고, 이 방에 소설이 아직 없을 때만
  // 참이다(서버가 셋을 함께 따진다). 이미 소설이 있는 방은 언제나 열 수 있다.
  novelCreationBlocked: boolean;
  // 다음 턴을 실제로 쓸 모델. 방에 저장한 모델을 지금 쓸 수 없으면(허용 회수·기능 꺼짐) 서버가 기본 모델로 바꿔 준 값이다.
  effectiveChatModel: ChatModelId;
  // 다음 턴 하나의 클로버(그 모델의 가격). undefined 는 서버가 값을 주지 않았다는 뜻이다 — 이 칸이 생기기 전의 서버가
  // 그렇다(서버와 화면은 따로 배포된다). 그때 화면은 가격 숫자를 말하지 않고 부족 여부도 판정하지 않는다.
  turnCost: number | undefined;
};
