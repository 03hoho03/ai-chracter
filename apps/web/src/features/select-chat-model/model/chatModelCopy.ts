import type { ChatModel, ChatModelId } from "@/entities/chat-model";

/** 선택지 한 줄에 붙는 가격. 하루 무료 대화가 없어 기본·상위 모델 모두 첫 턴부터 깎이므로, 두 모델을 가르는 것은
 * 단가뿐이라 가격만 말한다. */
export function formatChatModelPrice(model: ChatModel): string {
  return `턴마다 클로버 ${model.turnCost.toLocaleString()}개`;
}

/** 상위 모델로 바꾸기 직전의 확인 문장. 이 확인이 그 방의 클로버 사용 동의다 — 바꾼 뒤의 턴은 따로 묻지 않고 바로
 * 차감되므로, 단가를 여기서 말하지 않으면 이용자가 들을 자리가 다시 없다. */
export function formatPremiumModelConfirm(model: ChatModel): string {
  return `첫 턴부터 턴마다 클로버 ${model.turnCost.toLocaleString()}개를 써요. 바꾸면 다음 턴부터 따로 묻지 않고 바로 차감돼요.`;
}

/** 상위 모델 확인 블록에서 잔액이 그 모델의 한 턴 가격보다 적을 때 덧붙이는 안내. 바꾸는 것 자체는 막지 않는다 — 전송할
 * 때 서버가 잔액을 판정한다. 가격은 서버가 준 값이다. 클로버를 돌려준다는 말은 하지 않는다(정산이 시간 초과되거나 확인에
 * 실패한 턴은 차감이 남을 수 있다). */
export function formatPremiumModelShortage(model: Pick<ChatModel, "turnCost">): string {
  return `클로버가 부족해요. 바꿔 둘 수는 있지만, 이 모델로 답을 받으려면 턴마다 클로버 ${model.turnCost.toLocaleString()}개가 있어야 해요.`;
}

export type ChatModelBadge = "베타" | "사용 중";

/** 목록 행의 이름 뒤에 붙는 배지, 놓이는 순서대로. `베타` 는 서버의 `beta` 로만 정한다 — id 로 정하면 상위 모델이
 * 정식이 되는 날 화면을 따로 고쳐야 한다. `beta` 칸이 없는 옛 응답이면 붙이지 않는다. */
export function chatModelBadges(model: Pick<ChatModel, "id"> & { beta?: boolean }, currentModelId: ChatModelId): ChatModelBadge[] {
  const badges: ChatModelBadge[] = [];
  if (model.beta === true) badges.push("베타");
  if (model.id === currentModelId) badges.push("사용 중");
  return badges;
}
