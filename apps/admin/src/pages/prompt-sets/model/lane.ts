import type { components } from "@ai-character-chat/api-types";

/** legal `model/legalKind.ts:3-16` 선례 그대로. */
export type PromptLane = components["schemas"]["AdminPromptSetSummary"]["lane"];

/** 스키마에 레인이 늘면 이 `Record`가 컴파일 에러로 잡는다. */
export const PROMPT_LANE_LABELS: Record<PromptLane, string> = {
  story: "스토리",
  character: "캐릭터",
  publish_filter: "발행 검열",
};

export function isPromptLane(value: string): value is PromptLane {
  return value in PROMPT_LANE_LABELS;
}

export const PROMPT_LANES = Object.keys(PROMPT_LANE_LABELS).filter(isPromptLane);
