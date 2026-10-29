import type { AdminPromptRoutingResponse, RoomModel } from "./types";

/** 지금 운영에서 고를 수 없는 상위 모델의 방이라 안 읽히는 칸에 붙이는 말. 배정 표와 프롬프트 화면이 같은 문장을 쓴다. 상위 모델
 * 스위치가 꺼진 경우와, 켜져 있어도 그 모델을 채팅 공개 목록에서 뺀 경우에 함께 붙으므로 이유를 하나로 말하지 않는다. */
export const PREMIUM_OFF_UNREAD_COPY = "운영에서 고를 수 없는 모델이라 지금은 안 읽혀요";

/** 이 방의 칸이 지금 운영에서 실행되는가. 상위 모델(Sonnet·Opus) 방은 그 모델이 지금 채팅에서 보일 때만 그 모델로 돌고, 아니면
 * 기본 모델(Gemini)로 돌아 그 방의 칸은 하나도 실행되지 않는다. 보이는 상위 모델은 서버가 `chatVisibleModels` 로 내려 준다(상위 모델
 * 스위치가 꺼져 있으면 비었다). 배정 표 조회의 칸·체인 목록은 그와 무관하게 그 칸을 담으므로 화면이 이 값으로 가른다. */
export function isRoomLive(routing: Pick<AdminPromptRoutingResponse, "chatVisibleModels">, roomModel: RoomModel) {
  if (roomModel !== "sonnet" && roomModel !== "opus") return true;
  return routing.chatVisibleModels.includes(roomModel);
}
