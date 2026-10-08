import type { components } from "@ai-character-chat/api-types";

import type { PromptLane } from "./lane";

/** 세트의 모델 축. 레인 × 모델마다 초안·게시·복원·활성 판정이 따로인 독립 체인이다. */
export type PromptModel = components["schemas"]["AdminPromptSetSummary"]["model"];

/** 스키마에 모델이 늘면 이 `Record`가 컴파일 에러로 잡는다. */
export const PROMPT_MODEL_LABELS: Record<PromptModel, string> = {
  gemini: "Gemini",
  sonnet: "Claude Sonnet 4.6",
  opus: "Claude Opus 4.6",
};

export function isPromptModel(value: string): value is PromptModel {
  return value in PROMPT_MODEL_LABELS;
}

const PROMPT_MODELS = Object.keys(PROMPT_MODEL_LABELS).filter(isPromptModel);

/** 발행 심사는 모델을 고르지 않아 Gemini 세트 하나뿐이다(서버가 다른 모델을 422로 거부한다). */
export function promptModelsFor(lane: PromptLane): readonly PromptModel[] {
  return lane === "publish_filter" ? ["gemini"] : PROMPT_MODELS;
}

/** 한 화면에 체인 10개(스토리·캐릭터·소설 × 3 + 발행 심사)가 함께 있을 때 체인별 상태를 담는 키. */
export type PromptChainKey = `${PromptLane}:${PromptModel}`;

export function promptChainKey(lane: PromptLane, model: PromptModel): PromptChainKey {
  return `${lane}:${model}`;
}
