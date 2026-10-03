import { isApiError } from "@/shared/api/client";

/** 이용제한·삭제된 작품의 방에서 입력창 자리에 띄우는 안내. 기다려도 풀리지 않는 거부라 "다시 시도"를 말하지 않고,
 * 사용자가 아직 할 수 있는 일(지난 대화 보기)을 함께 말한다. */
export const CONTENT_RESTRICTED_NOTICE = "이용이 제한된 작품이라 대화를 이어갈 수 없어요. 지난 대화는 그대로 볼 수 있어요.";

/** 같은 작품으로 새 방을 열려다 막혔을 때의 토스트(새 대화 시작·시작설정 변경 모두 새 방을 만든다). */
export const CONTENT_RESTRICTED_START_MESSAGE = "이용이 제한된 작품이라 새 대화를 시작할 수 없어요.";

/** BE 가 이용제한·삭제된 작품에서 전송·재생성·편집·새 방·시작설정 변경을 거부할 때 내는
 * 403 `{"detail": {"code": "CONTENT_RESTRICTED"}}` 인가. 같은 403 을 정지(`detail` 이 문자열)와 재동의(다른 code)도
 * 내므로 status 만으로 가르지 않고 detail 의 code 까지 본다 — 좁히기 형태는 `isLegalReconsentRequiredError` 와 같다. */
export function isContentRestrictedError(error: unknown): boolean {
  return hasForbiddenCode(error, "CONTENT_RESTRICTED");
}

/** 작가가 아닌 사람이 비공개 작품(작가 탈퇴로 비공개가 된 작품 포함)에 새 방을 열려다 막혔을 때의 문구. 새 대화
 * 시작과 시작설정 변경 둘 다 새 방을 만들어 같이 막히므로 두 경로에 쓴다. 이미 있는 방에서 대화를 잇는 것은 막히지
 * 않는다. */
export const CONTENT_PRIVATE_START_MESSAGE = "비공개 작품이라 새 대화를 시작할 수 없어요.";

/** 새 방을 만드는 두 요청(`POST /chat-rooms`, `POST /chat-rooms/{id}/change-starting-setup`)의 실패 토스트 문구.
 * 이용제한·비공개는 기다려도 안 풀리므로 호출부의 "잠시 후 다시" 문구(`fallback`)를 쓰지 않는다. */
export function toStartChatErrorMessage(error: unknown, fallback: string): string {
  if (hasForbiddenCode(error, "CONTENT_RESTRICTED")) return CONTENT_RESTRICTED_START_MESSAGE;
  if (hasForbiddenCode(error, "CONTENT_PRIVATE")) return CONTENT_PRIVATE_START_MESSAGE;
  return fallback;
}

function hasForbiddenCode(error: unknown, code: string): boolean {
  const apiError = isApiError(error) ? error : undefined;
  if (apiError?.status !== 403 || !apiError.detail || typeof apiError.detail !== "object") return false;
  return apiError.detail.code === code;
}
