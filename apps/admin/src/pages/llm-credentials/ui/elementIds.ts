import type { MoveDirection } from "../model/status";

/** 저장소 안내 띠의 문장. 저장소가 있어야 하는 버튼(자격 추가·키 교체·확인 호출·목록 사용 켜기)이 막힐 때 이 문장을 설명으로 단다. */
export const STORE_NOTICE_ID = "llm-credentials-store-notice";
export const POOL_HEADING_ID = "llm-credentials-pool-heading";
export const ORDER_HEADING_ID = "llm-credentials-order-heading";

function itemPrefix(credentialId: string) {
  return `llm-credential-${credentialId}`;
}

/** 항목 이름(h3). 추가가 끝나면 새 항목의 이 제목으로 포커스를 옮긴다. */
export function credentialHeadingId(credentialId: string) {
  return `${itemPrefix(credentialId)}-heading`;
}

export function moveButtonId(credentialId: string, direction: MoveDirection) {
  return `${itemPrefix(credentialId)}-move-${direction}`;
}

export function checkButtonId(credentialId: string) {
  return `${itemPrefix(credentialId)}-check`;
}

export function checkHintId(credentialId: string) {
  return `${itemPrefix(credentialId)}-check-hint`;
}

export function enableBlockerId(credentialId: string) {
  return `${itemPrefix(credentialId)}-enable-blocker`;
}

export function providerNoteId(credentialId: string) {
  return `${itemPrefix(credentialId)}-provider-note`;
}
