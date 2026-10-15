import { isChatTurnInProgressError } from "@/entities/chat-room";
import { isLegalReconsentRequiredError } from "@/entities/legal";
import { isApiError } from "@/shared/api/client";

/** 되돌리기 실패를 화면이 어떻게 받는가. `message` 가 없으면 토스트를 띄우지 않고, `refetchRoom` 이면 방을 다시 받는다. */
export type RestorePreviousResponseFailure = {
  message: string | undefined;
  refetchRoom: boolean;
};

export const RESTORE_PREVIOUS_RESPONSE_SUCCESS_MESSAGE = "방금 전 답변으로 돌아갔어요";

/** 되돌리기 실패를 토스트 문구와 방 재조회 여부로 옮긴다.
 *
 * - 되돌릴 답이 없어졌으면(그 사이 대화가 바뀌었거나 화면이 낡았다) 방을 다시 받아 메뉴 항목을 서버 값에 맞춰 걷는다.
 * - 앞 턴이 돌고 있으면 기다리면 풀리므로 재조회 없이 끝난 뒤 다시 하라고만 한다. 보내기 배너의 문구는 "다시 보내 주세요"라
 *   여기서는 맞지 않아 따로 쓴다.
 * - 재동의 403 은 전역 뮤테이션 오류 처리가 재동의 창을 띄우므로 여기서는 말하지 않는다. */
export function toRestorePreviousResponseFailure(error: unknown): RestorePreviousResponseFailure {
  if (isLegalReconsentRequiredError(error)) return { message: undefined, refetchRoom: false };
  if (isChatTurnInProgressError(error)) {
    return { message: "아직 앞의 응답을 만들고 있어요 · 끝나면 다시 해 주세요", refetchRoom: false };
  }
  const apiError = isApiError(error) ? error : undefined;
  if (
    apiError?.status === 409 &&
    typeof apiError.detail === "object" &&
    apiError.detail?.code === "PREVIOUS_RESPONSE_UNAVAILABLE"
  ) {
    return { message: "방금 전 답변으로 돌아갈 수 없어요. 그 사이 대화가 바뀌었어요.", refetchRoom: true };
  }
  if (apiError?.status === 404) return { message: "대화방을 찾을 수 없어요.", refetchRoom: false };
  return { message: "답변을 되돌리지 못했어요. 잠시 후 다시 시도해주세요.", refetchRoom: false };
}
