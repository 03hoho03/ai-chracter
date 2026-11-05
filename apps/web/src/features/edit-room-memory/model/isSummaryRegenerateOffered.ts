import type { ChatRoomMemory } from "@/entities/chat-room";

/** 요약 다시 만들기 버튼을 보일지. 라우트가 장면·사실 목록과 같은 스위치 뒤에 있고(`itemsVisible`), 요약 접기가 꺼진 방
 * (`summaryFolding` 거짓)에서는 요약이 응답에 쓰이지 않아 다시 만들어도 쓰이지 않는 것에 클로버를 쓰게 된다 — 그래서 둘 다
 * 참일 때만 보인다. */
export function isSummaryRegenerateOffered(features: ChatRoomMemory["features"]): boolean {
  return features.itemsVisible && features.summaryFolding;
}
