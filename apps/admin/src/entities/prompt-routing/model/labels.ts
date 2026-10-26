import type {
  PromptSetModelId,
  RoomModel,
  RouteBackend,
  RouteSkipReason,
  RouteSource,
  RoutingLane,
  RoutingStage,
} from "./types";

// 전부 `satisfies Record<유니언, string>` 이다 — BE 에 단계·경로·출처가 늘면 api-types 를 다시 만드는 순간 컴파일이 깨진다.

export const ROUTING_STAGE_LABELS = {
  chat_generate: "응답 생성",
  stat_judgment: "스탯 판정",
  scene_judgment: "장면 헤더",
  ending_judgment: "엔딩 판정",
  situational_image: "상황 이미지 판정",
  media_book_image: "미디어 북 칸 판정",
  memory_summary: "기억 요약",
  memory_episode: "장면 기억 추출",
  memory_fact: "사실 기억 추출",
  novel_chapter: "소설 화 생성",
  novel_outline: "소설 전체 구성안",
  novel_episode_outline: "소설 장면 구성안",
  novel_revise: "소설 문단 수정",
  novel_revise_blocks: "소설 여러 문단 수정",
  novel_recheck: "소설 다시 검사",
  novel_boundary: "소설 화 경계 제안",
} satisfies Record<RoutingStage, string>;

/** 프롬프트 화면의 레인 이름과 같은 말이다. 값은 같아도 타입이 배정 표의 레인뿐이라 따로 둔다. */
export const ROUTING_LANE_LABELS = {
  story: "스토리",
  character: "캐릭터",
  novel: "소설",
} satisfies Record<RoutingLane, string>;

export const ROOM_MODEL_LABELS = {
  gemini: "Gemini 방",
  sonnet: "Sonnet 방",
  opus: "Opus 방",
  any: "모든 작업 모델",
} satisfies Record<RoomModel, string>;

/** 체인의 모델 이름. 프롬프트 화면의 모델 탭과 배정 표의 읽을 체인·부를 모델이 이 한 곳을 읽는다. */
export const PROMPT_MODEL_LABELS = {
  gemini: "Gemini",
  sonnet: "Claude Sonnet 5.5",
  opus: "Claude Opus 5.5",
  haiku: "Claude Haiku · 판정 전용",
} satisfies Record<PromptSetModelId, string>;

export const ROUTE_BACKEND_LABELS = {
  gemini: "Google 직결",
  anthropic: "Anthropic 직결",
  bedrock: "Bedrock",
} satisfies Record<RouteBackend, string>;

export const ROUTE_SOURCE_LABELS = {
  row: "이 칸의 행",
  inherited: "물려받음(스탯 판정 행)",
  env: "env 기본값",
  room: "방 모델",
} satisfies Record<RouteSource, string>;

export const ROUTE_SKIP_REASON_LABELS = {
  "pair-not-allowed": "허용하지 않는 모델·경로",
  "backend-mismatch": "지금 env 경로와 다름",
  "structured-effort": "구조화 깊이 범위 밖",
} satisfies Record<RouteSkipReason, string>;

export function isPromptSetModelId(value: string): value is PromptSetModelId {
  return value in PROMPT_MODEL_LABELS;
}

export function isRoutingLane(value: string): value is RoutingLane {
  return value in ROUTING_LANE_LABELS;
}

/** 배정 표가 채팅 턴의 칸을 고르는 레인. 소설 레인도 배정 표에 행이 있지만 프롬프트 세트 화면은 그 레인의 체인을 배정 표
 * 조회로 설명하지 않고 고정 문구로 다루므로, 프롬프트 세트 화면은 이 목록으로 채팅 레인을 가른다. */
export const CHAT_ROUTING_LANES = ["story", "character"] as const satisfies readonly RoutingLane[];

export type ChatRoutingLane = (typeof CHAT_ROUTING_LANES)[number];

export function isChatRoutingLane(value: string): value is ChatRoutingLane {
  return CHAT_ROUTING_LANES.some((lane) => lane === value);
}
