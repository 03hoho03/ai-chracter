import type { components } from "@ai-character-chat/api-types";

import { isNovelPromptModel, PROMPT_MODEL_LABELS } from "@/entities/prompt-routing";

import type { PromptLane } from "./lane";

/** 세트의 모델 축. 레인 × 모델마다 초안·게시·복원·활성 판정이 따로인 독립 체인이다. 글쓰기 모델 셋에 판정 전용
 * 모델(`haiku` — 판정·요약 문안만 있고 그 모델로는 글을 쓰지 않는다)이 더해진다. */
export type PromptModel = components["schemas"]["AdminPromptSetSummary"]["model"];

/** 모델 이름은 배정 표 화면과 같은 말이라 한 곳(`entities/prompt-routing`)에 두고 여기서는 다시 내보낸다. */
export { PROMPT_MODEL_LABELS };

export function isPromptModel(value: string): value is PromptModel {
  return value in PROMPT_MODEL_LABELS;
}

const PROMPT_MODELS = Object.keys(PROMPT_MODEL_LABELS).filter(isPromptModel);

/** 심사 레인(발행 심사·노벨 심사)은 모델을 고르지 않아 Gemini 세트 하나뿐이다. 판정 전용 모델은 채팅 판정·요약 문안이고 Haiku
 * 글쓰기는 채팅 전용이라 둘 다 스토리·캐릭터 레인에만 있다(서버가 그 밖의 조합을 422로 거부한다). */
export function promptModelsFor(lane: PromptLane): readonly PromptModel[] {
  if (lane === "publish_filter" || lane === "novel_screen") return ["gemini"];
  if (lane === "novel") return PROMPT_MODELS.filter(isNovelPromptModel);
  return PROMPT_MODELS;
}

/** 한 화면에 체인 15개(스토리·캐릭터 × 5 + 소설 × 3 + 발행 심사·노벨 심사)가 함께 있을 때 체인별 상태를 담는 키. */
export type PromptChainKey = `${PromptLane}:${PromptModel}`;

export function promptChainKey(lane: PromptLane, model: PromptModel): PromptChainKey {
  return `${lane}:${model}`;
}
