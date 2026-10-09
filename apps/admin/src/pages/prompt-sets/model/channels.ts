import type { PromptLane } from "./lane";

/** 코드가 아는 11채널(어드민은 이 집합을 늘리거나 줄이지
 * 못한다). 목록·라벨·술어를 손으로 따로 적지 않고 `PROMPT_CHANNEL_LABELS`에서 도출해야 셋이
 * 어긋날 수 없다(legal의 `LEGAL_KIND_LABELS`와 같은 패턴). */
export const PROMPT_CHANNEL_LABELS = {
  system: "시스템 지침",
  generation: "생성",
  // 옛 절대값 판정 채널. 채팅은 더 이상 이 문안을 읽지 않지만 운영 세트에 행이 남아 있어 탭이 보인다 — 고쳐도 아무 일이 없다는
  // 것을 라벨로 알린다(서버는 게시 검증용으로만 이 행을 받는다).
  stat_judgment: "스탯 판정(사용 안 함)",
  stat_rule_judgment: "스탯 규칙 판정",
  ending_judgment: "엔딩 판정",
  image_judgment: "이미지 판정",
  memory_summary: "기억 요약",
  publish_filter: "발행 검열",
  novelize_boundary: "소설 경계 제안",
  novelize_chapter: "소설 화 생성",
  novelize_revise: "소설 문단 수정",
} as const;

export type PromptChannel = keyof typeof PROMPT_CHANNEL_LABELS;

export function isPromptChannel(value: string): value is PromptChannel {
  return value in PROMPT_CHANNEL_LABELS;
}

export const PROMPT_CHANNELS = Object.keys(PROMPT_CHANNEL_LABELS).filter(isPromptChannel);

const NOVEL_CHANNELS: ReadonlySet<PromptChannel> = new Set(["novelize_boundary", "novelize_chapter", "novelize_revise"]);

/** 이 레인 편집기에 탭으로 보일 채널인가. 스토리·캐릭터 레인의 Gemini 초안에는 옛 소설 문안 행이 그대로 실려 오지만
 * 소설 문안은 이제 소설 레인에서 고친다 — 그 행은 옛 이미지로 되돌렸을 때 옛 코드가 읽는 값이라 서버가 저장·게시 때
 * 직전 게시본 값으로 갈아 끼운다. 탭으로 보이면 고쳐도 아무 일도 없는 칸이 되어 숨긴다(폼 값에는 남아 저장 때 함께
 * 가고, 서버가 버린다). */
export function isChannelEditableInLane(lane: PromptLane, channel: PromptChannel): boolean {
  return lane === "novel" || lane === "publish_filter" || !NOVEL_CHANNELS.has(channel);
}

/** `scope` 세 값. 섹션 자체는 채널 하나에 스토리/캐릭터가 공유(`both`)되거나 갈리는
 * (`story`/`character`) 행으로 존재한다 — 어드민이 만드는 값이 아니라 표시 전용이다.
 * BE `scope: str`을 좁히지 않는 **로컬** 유니온이라
 * `as const`로 타입·술어·목록 3종 세트를 도출한다(channel과 같은 패턴). */
export const PROMPT_SCOPE_LABELS = {
  both: "공통",
  story: "스토리",
  character: "캐릭터",
} as const;

export type PromptScope = keyof typeof PROMPT_SCOPE_LABELS;

export function isPromptScope(value: string): value is PromptScope {
  return value in PROMPT_SCOPE_LABELS;
}

export const PROMPT_SCOPES = Object.keys(PROMPT_SCOPE_LABELS).filter(isPromptScope);
