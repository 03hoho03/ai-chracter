import type { components } from "@ai-character-chat/api-types";

type ChatModelItem = components["schemas"]["ChatModelItem"];

/** 글쓰기 모델의 레지스트리 id. 서버가 방·작업에 저장하고 주고받는 불투명 값이다(공급사 모델명이 아니다). */
export type ChatModelId = ChatModelItem["id"];

/** 서버가 새 방에 쓰는 기본 모델. 하루 무료 대화는 없어 어느 모델이든 첫 턴부터 클로버를 쓰고, 모델 차이는 단가뿐이다.
 * 목록이 없는 자리(방 응답의 빈 칸 채우기, 미리보기의 처음 값)에서만 쓴다 — 목록이 있으면 `defaultChatModelId` 로 서버가
 * 정한 기본 모델을 읽는다. */
export const DEFAULT_CHAT_MODEL: ChatModelId = "gemini";

/** 모델 목록에서 서버의 기본 모델 id. `isDefault` 칸이 없는 옛 응답이면 첫 항목이다(서버는 기본 모델을 언제나 맨 앞에
 * 둔다). 목록이 없거나 비면 undefined.
 *
 * 판정은 행마다 `isDefault` 를 읽지 말고 이 id 와 비교한다. 생성 타입이 그 칸을 필수로 적어 옛 응답의 `undefined` 를
 * 타입이 잡지 못하므로, 행마다 읽으면 칸이 없는 서버로 되돌렸을 때 기본 모델까지 "기본이 아님"이 되어 기본 모델로
 * 돌아갈 때도 클로버 확인이 뜬다. */
export function defaultChatModelId(
  models: readonly Pick<ChatModelItem, "id" | "isDefault">[] | undefined,
): ChatModelId | undefined {
  return models?.find((model) => model.isDefault === true)?.id ?? models?.[0]?.id;
}

/** 이 모델이 서버의 기본 모델인가. 목록이 없으면 undefined — 모른다는 것을 호출부가 정한다(확인을 붙일지 등). */
export function isDefaultChatModel(
  models: readonly Pick<ChatModelItem, "id" | "isDefault">[] | undefined,
  modelId: ChatModelId,
): boolean | undefined {
  const defaultId = defaultChatModelId(models);
  return defaultId === undefined ? undefined : modelId === defaultId;
}

/** 목록에서 기본 모델 한 턴의 클로버. 목록이 아직 없거나 기본 모델이 빠져 있으면 undefined — 화면이 숫자 없이
 * 말한다. */
export function defaultChatTurnCost(models: readonly { id: ChatModelId; turnCost: number }[] | undefined): number | undefined {
  return models?.find((model) => model.id === DEFAULT_CHAT_MODEL)?.turnCost;
}
