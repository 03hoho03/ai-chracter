import {
  DEFAULT_CHAT_MODEL,
  defaultChatModelId,
  isDefaultChatModel,
  type ChatModel,
  type ChatModelId,
} from "@/entities/chat-model";
import type { PreviewStartQuery } from "@/entities/preview-session";
import { hasEnabledFeature, type EnabledFeature } from "@/entities/session";

type ModelList = readonly Pick<ChatModel, "id" | "isDefault">[] | undefined;

/** 이 계정이 미리보기에서 모델을 고를 수 있는가. 대화방 모델 칩과 같은 기능(상위 모델 허용 스위치)으로 정한다 — 꺼져
 * 있으면 미리보기에 모델 칩이 없고 서버도 기본 모델로만 돈다. */
export function isPreviewModelSelectable(enabledFeatures: readonly EnabledFeature[] | undefined): boolean {
  return hasEnabledFeature(enabledFeatures, "chat_premium_models");
}

/** 미리보기가 지금 실제로 답을 쓰는 모델. 고른 모델은 저장해 두기만 하고, 화면에 보일 모델은 매번 이 식으로 정한다.
 *
 * 서버는 턴마다 세션에 저장된 모델을 지금 채팅에서 보이는 모델인지(상위 모델 총 스위치와 공개 목록) 다시 판정해, 아니면
 * 기본 모델로 돌린다. 모델 목록이 같은 판정으로 실려 오므로, 목록이 있으면 고른 모델이 목록에 있는지로 정한다 — 총
 * 스위치는 켜진 채 그 모델 하나만 공개 목록에서 빠져도 칩·잔량·확인 단가가 서버가 실제로 쓰는 모델을 따라간다(목록은
 * 창 포커스마다 다시 읽힌다). 목록이 아직 없으면 세션의 기능 목록(총 스위치)으로만 정한다. */
export function previewDisplayModel(
  enabledFeatures: readonly EnabledFeature[] | undefined,
  chosenModelId: ChatModelId,
  models: ModelList,
): ChatModelId {
  if (models !== undefined) {
    if (models.some((model) => model.id === chosenModelId)) return chosenModelId;
    return defaultChatModelId(models) ?? DEFAULT_CHAT_MODEL;
  }
  if (chosenModelId === DEFAULT_CHAT_MODEL) return chosenModelId;
  return isPreviewModelSelectable(enabledFeatures) ? chosenModelId : DEFAULT_CHAT_MODEL;
}

/** 고른 모델을 기본 모델로 되돌려야 하면 그 기본 모델 id, 아니면 undefined. 고른 모델이 목록에서 빠지면 화면은 이미
 * 기본 모델을 말하지만(`previewDisplayModel`), 고른 값까지 되돌리지 않으면 그 모델이 다시 공개될 때 다음 세션이 확인 없이
 * 더 비싼 모델로 열린다 — 확인은 고른 그 순간의 동의라 다시 고를 때 다시 묻는다. 목록이 없거나 비면 판정하지 않는다.
 * 세션이 이미 열려 있으면 부르지 않는다 — 서버가 세션에 저장한 모델로 돌아가므로 화면도 고른 값을 따라가야 한다. */
export function previewChosenModelReset(models: ModelList, chosenModelId: ChatModelId): ChatModelId | undefined {
  const defaultId = defaultChatModelId(models);
  if (models === undefined || defaultId === undefined) return undefined;
  return models.some((model) => model.id === chosenModelId) ? undefined : defaultId;
}

/** 미리보기에서 이 모델로 바꾸기 전에 확인을 받을지. 기본 모델이 아닌 모델은 대화방과 같은 이유(클로버 사용 동의)로
 * 언제나 묻고(목록으로 기본 모델인지 정할 수 없을 때도 묻는다), 기본 모델로 돌아가는 것은 돈이 덜 드는 쪽이라 대화방처럼
 * 묻지 않는다 — 다만 진행 중인 미리보기 대화가 있으면 모델을 바꾸는 것이 곧 그 대화를 버리고 처음부터 다시 시작하는
 * 것이라 그때는 기본 모델로 가도 묻는다. */
export function previewModelNeedsConfirm(models: ModelList, modelId: ChatModelId, hasSession: boolean): boolean {
  return isDefaultChatModel(models, modelId) !== true || hasSession;
}

/** 미리보기 세션을 여는 요청의 쿼리. 기본 모델이면 쿼리를 싣지 않는다(서버의 쿼리 기본값이 기본 모델이다). 목록이 없어
 * 기본 모델인지 모르면 고른 모델을 싣는다 — 서버가 그 모델을 그대로 판정한다. */
export function previewStartQuery(models: ModelList, modelId: ChatModelId): PreviewStartQuery | undefined {
  return isDefaultChatModel(models, modelId) === true ? undefined : { model: modelId };
}

/** 이 모델로 한 턴을 보낼 때 드는 클로버(서버 모델 목록의 값). 목록이 아직 없거나 그 모델이 빠져 있으면 undefined —
 * 확인 문구가 숫자 없이 말한다. */
export function previewTurnCost(
  models: readonly { id: ChatModelId; turnCost: number }[] | undefined,
  modelId: ChatModelId,
): number | undefined {
  return models?.find((model) => model.id === modelId)?.turnCost;
}
