/** prompt-db-goal-prompt.md §4-1 — 코드가 아는 6채널(D-7, 어드민은 이 집합을 늘리거나 줄이지
 * 못한다). 목록·라벨·술어를 손으로 따로 적지 않고 `PROMPT_CHANNEL_LABELS`에서 도출해야 셋이
 * 어긋날 수 없다(legal의 `LEGAL_KIND_LABELS`와 같은 패턴). */
export const PROMPT_CHANNEL_LABELS = {
  system: "시스템 지침",
  generation: "생성",
  stat_judgment: "스탯 판정",
  ending_judgment: "엔딩 판정",
  image_judgment: "이미지 판정",
  publish_filter: "발행 검열",
} as const;

export type PromptChannel = keyof typeof PROMPT_CHANNEL_LABELS;

export function isPromptChannel(value: string): value is PromptChannel {
  return value in PROMPT_CHANNEL_LABELS;
}

export const PROMPT_CHANNELS = Object.keys(PROMPT_CHANNEL_LABELS).filter(isPromptChannel);

/** §4-2의 `scope` 세 값. 섹션 자체는 채널 하나에 스토리/캐릭터가 공유(`both`)되거나 갈리는
 * (`story`/`character`) 행으로 존재한다 — 어드민이 만드는 값이 아니라 표시 전용이다. */
export const PROMPT_SCOPE_LABELS: Record<string, string> = {
  both: "공통",
  story: "스토리",
  character: "캐릭터",
};
