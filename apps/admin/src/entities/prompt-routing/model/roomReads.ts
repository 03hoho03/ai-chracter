import type { AdminPromptRoutingResponse, RoomModel } from "./types";

/** 상위 모델 스위치가 꺼져 지금 운영에서 안 읽히는 칸에 붙이는 말. 배정 표와 프롬프트 화면이 같은 문장을 쓴다. */
export const PREMIUM_OFF_UNREAD_COPY = "상위 모델이 꺼져 있어 지금은 안 읽혀요";

/** 이 방의 칸이 지금 운영에서 실행되는가. 채팅 상위 모델 스위치가 꺼지면 Opus 방은 기본 모델(Gemini)로 돌아 Opus 방의 칸은
 * 하나도 실행되지 않는다. 배정 표 조회의 칸·체인 목록은 스위치와 무관하게 그 칸을 담으므로 화면이 이 값으로 가른다. */
export function isRoomLive(routing: Pick<AdminPromptRoutingResponse, "chatPremiumModelsEnabled">, roomModel: RoomModel) {
  return routing.chatPremiumModelsEnabled || roomModel !== "opus";
}
