import type { components } from "@ai-character-chat/api-types";

import type { PromptLane } from "./lane";

/** 세트의 모델 축. 레인 × 모델마다 초안·게시·복원·활성 판정이 따로인 독립 체인이다. 글쓰기 모델 셋에 판정 전용
 * 모델(`haiku` — 판정·요약 문안만 있고 그 모델로는 글을 쓰지 않는다)이 더해진다. */
export type PromptModel = components["schemas"]["AdminPromptSetSummary"]["model"];

/** 스키마에 모델이 늘면 이 `Record`가 컴파일 에러로 잡는다. */
export const PROMPT_MODEL_LABELS: Record<PromptModel, string> = {
  gemini: "Gemini",
  sonnet: "Claude Sonnet 5.5",
  opus: "Claude Opus 5.5",
  haiku: "Claude Haiku 4.5 · 판정 전용",
};

export function isPromptModel(value: string): value is PromptModel {
  return value in PROMPT_MODEL_LABELS;
}

const PROMPT_MODELS = Object.keys(PROMPT_MODEL_LABELS).filter(isPromptModel);

/** 심사 레인(발행 심사·노벨 심사)은 모델을 고르지 않아 Gemini 세트 하나뿐이다. 판정 전용 모델은 채팅 판정·요약 문안이라
 * 스토리·캐릭터 레인에만 있다(서버가 그 밖의 조합을 422로 거부한다). */
export function promptModelsFor(lane: PromptLane): readonly PromptModel[] {
  if (lane === "publish_filter" || lane === "novel_screen") return ["gemini"];
  if (lane === "novel") return PROMPT_MODELS.filter((model) => model !== "haiku");
  return PROMPT_MODELS;
}

/** 한 화면에 체인 13개(스토리·캐릭터 × 4 + 소설 × 3 + 발행 심사·노벨 심사)가 함께 있을 때 체인별 상태를 담는 키. */
export type PromptChainKey = `${PromptLane}:${PromptModel}`;

export function promptChainKey(lane: PromptLane, model: PromptModel): PromptChainKey {
  return `${lane}:${model}`;
}
