import { isPremiumChatModel, type ChatModel } from "@/entities/chat-model";

/** 선택지 한 줄에 붙는 가격. 기본 모델과 상위 모델은 같은 "턴마다 N개"여도 언제부터 깎이는지가 다르다 — 기본
 * 모델은 하루 무료 대화를 다 쓴 뒤부터, 상위 모델은 첫 턴부터다. 숫자만 나란히 두면 그 차이가 안 보인다.
 *
 * `identityGated` 는 서버가 세션에 실은 "본인인증 게이트에 걸렸는가"다. 걸린 회원은 기본 모델도 무료 대화가 없어
 * "다 쓴 뒤"가 거짓이라 첫 턴부터 깎인다고 말한다. */
export function formatChatModelPrice(model: ChatModel, identityGated: boolean): string {
  const perTurn = `턴마다 클로버 ${model.turnCost.toLocaleString()}개`;
  if (isPremiumChatModel(model.id)) return `${perTurn} · 무료 대화 없음`;
  return identityGated ? `${perTurn} · 본인인증 전에는 무료 대화 없음` : `무료 대화를 다 쓴 뒤 ${perTurn}`;
}

/** 상위 모델로 바꾸기 직전의 확인 문장. 이 확인이 그 방의 클로버 사용 동의다 — 바꾼 뒤의 턴은 하루 한 번 확인
 * 없이 바로 차감되므로, 그 사실을 여기서 말하지 않으면 이용자가 들을 자리가 다시 없다. */
export function formatPremiumModelConfirm(model: ChatModel): string {
  return `무료 대화 없이 첫 턴부터 턴마다 클로버 ${model.turnCost.toLocaleString()}개를 써요. 바꾸면 다음 턴부터 따로 묻지 않고 바로 차감돼요.`;
}
