import { DEFAULT_CHAT_MODEL, isPremiumChatModel, type ChatModelId } from "@/entities/chat-model";
import type { PreviewStartQuery } from "@/entities/preview-session";
import { hasEnabledFeature, type EnabledFeature } from "@/entities/session";

/** 이 계정이 미리보기에서 모델을 고를 수 있는가. 대화방 모델 칩과 같은 기능(상위 모델 허용 스위치)으로 정한다 — 꺼져
 * 있으면 미리보기에 모델 칩이 없고 서버도 기본 모델로만 돈다. */
export function isPreviewModelSelectable(enabledFeatures: readonly EnabledFeature[] | undefined): boolean {
  return hasEnabledFeature(enabledFeatures, "chat_premium_models");
}

/** 미리보기가 지금 실제로 답을 쓰는 모델. 고른 모델은 저장해 두기만 하고, 화면에 보일 모델은 매번 이 식으로 정한다.
 *
 * 서버는 턴마다 세션에 저장된 모델을 상위 모델 허용 스위치로 다시 판정해, 꺼져 있으면 기본 모델로 돌린다. 세션의 기능
 * 목록에 같은 스위치가 실려 오므로 같은 식을 쓰면 스위치가 미리보기 도중 꺼져도(세션은 창 포커스마다 다시 읽힌다)
 * 칩·잔량·확인 단가가 서버가 실제로 쓰는 모델을 따라간다. 판정 기능은 대화방 모델 칩과 같은 것이다. */
export function previewDisplayModel(
  enabledFeatures: readonly EnabledFeature[] | undefined,
  chosenModelId: ChatModelId,
): ChatModelId {
  if (!isPremiumChatModel(chosenModelId)) return chosenModelId;
  return isPreviewModelSelectable(enabledFeatures) ? chosenModelId : DEFAULT_CHAT_MODEL;
}

/** 미리보기에서 이 모델로 바꾸기 전에 확인을 받을지. 상위 모델은 대화방과 같은 이유(클로버 사용 동의)로 언제나 묻고,
 * 기본 모델로 돌아가는 것은 돈이 덜 드는 쪽이라 대화방처럼 묻지 않는다 — 다만 진행 중인 미리보기 대화가 있으면 모델을
 * 바꾸는 것이 곧 그 대화를 버리고 처음부터 다시 시작하는 것이라 그때는 기본 모델로 가도 묻는다. */
export function previewModelNeedsConfirm(modelId: ChatModelId, hasSession: boolean): boolean {
  return isPremiumChatModel(modelId) || hasSession;
}

/** 미리보기 세션을 여는 요청의 쿼리. 기본 모델이면 쿼리를 싣지 않아 모델 선택이 생기기 전과 같은 요청이 나간다 — 모델
 * 쿼리를 모르는 서버와 새 화면이 겹치는 동안에도 기본 모델 경로는 바뀌지 않는다. */
export function previewStartQuery(modelId: ChatModelId): PreviewStartQuery | undefined {
  return isPremiumChatModel(modelId) ? { model: modelId } : undefined;
}

/** 이 모델로 한 턴을 보낼 때 드는 클로버(서버 모델 목록의 값). 목록이 아직 없거나 그 모델이 빠져 있으면 undefined —
 * 확인 문구가 숫자 없이 말한다. */
export function previewTurnCost(
  models: readonly { id: ChatModelId; turnCost: number }[] | undefined,
  modelId: ChatModelId,
): number | undefined {
  return models?.find((model) => model.id === modelId)?.turnCost;
}
