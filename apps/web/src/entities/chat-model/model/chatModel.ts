import type { components } from "@ai-character-chat/api-types";

/** 글쓰기 모델의 레지스트리 id. 서버가 방·작업에 저장하고 주고받는 불투명 값이다(공급사 모델명이 아니다). */
export type ChatModelId = components["schemas"]["ChatModelItem"]["id"];

/** 서버가 새 방에 쓰는 기본 모델. 하루 무료 대화와 하루 한 번 클로버 사용 확인은 이 모델에만 있다. */
export const DEFAULT_CHAT_MODEL: ChatModelId = "gemini";

/** 기본 모델이 아닌 모델은 턴마다 클로버를 쓴다 — 무료 대화가 없고, 고를 때 한 번 확인한 뒤로는 묻지 않는다. */
export function isPremiumChatModel(modelId: ChatModelId): boolean {
  return modelId !== DEFAULT_CHAT_MODEL;
}

/** 목록에서 기본 모델 한 턴의 클로버. 목록이 아직 없거나 기본 모델이 빠져 있으면 undefined — 화면이 숫자 없이
 * 말한다. */
export function defaultChatTurnCost(models: readonly { id: ChatModelId; turnCost: number }[] | undefined): number | undefined {
  return models?.find((model) => model.id === DEFAULT_CHAT_MODEL)?.turnCost;
}
