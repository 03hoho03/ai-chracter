import { isApiError } from "@/shared/api/client";

/** 같은 방에 앞 턴이 아직 돌고 있어 이번 보내기·수정·재생성이 시작도 못 하고 거절됐을 때 배너 문구. 실패가 아니라
 * 기다리면 풀리는 일이라 "실패했습니다"를 쓰지 않고, 다음 행동(끝나면 다시 보내기)만 말한다. 원인이 다른 창이든 같은
 * 탭(응답 중 방을 떠났다 돌아옴)이든 참인 문장이다. */
export const CHAT_TURN_IN_PROGRESS_NOTICE = "아직 앞의 응답을 만들고 있어요 · 끝나면 다시 보내 주세요";

/** BE 가 같은 방의 진행 중 턴 때문에 스트림을 열기 전에 내는 409 `{"detail": {"code": "CHAT_TURN_IN_PROGRESS"}}` 인가.
 * 409 는 기억 편집 충돌 등 다른 code 로도 오므로 status 만으로 가르지 않고 code 까지 본다. */
export function isChatTurnInProgressError(error: unknown): boolean {
  const apiError = isApiError(error) ? error : undefined;
  if (apiError?.status !== 409 || !apiError.detail || typeof apiError.detail !== "object") return false;
  return apiError.detail.code === "CHAT_TURN_IN_PROGRESS";
}
