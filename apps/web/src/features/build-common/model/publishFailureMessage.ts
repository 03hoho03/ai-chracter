import { isApiError } from "@/shared/api/client";
import { getRateLimitDetail } from "@/shared/api/rateLimit";

const SCREENING_UNAVAILABLE_CODE = "PUBLISH_SCREENING_UNAVAILABLE";
const PUBLISH_CONFLICT_CODE = "PUBLISH_CONFLICT";

/** 서버 503 바디에 `message` 가 없을 때 쓰는 같은 뜻의 문구. */
export const PUBLISH_SCREENING_UNAVAILABLE_MESSAGE = "발행 심사를 지금 진행하지 못했어요. 잠시 뒤 다시 발행해 주세요.";

/** 서버 409 `PUBLISH_CONFLICT` 의 문구. 서버 바디에는 code 만 있고 문구는 여기 한 곳에만 둔다. */
export const PUBLISH_CONFLICT_MESSAGE =
  "발행하는 사이에 이미지가 바뀌었거나 다른 창에서 먼저 발행됐어요. 확인한 뒤 다시 발행해 주세요.";

/** 발행 요청 자체의 실패 → 토스트 문구. 판별할 수 없으면 `undefined` 이고 호출부가 일반 실패 문구로 보낸다.
 *
 * - 429(`window: "publish"`): 심사 호출의 시간당 상한. 일반 실패 문구는 "잠시 후"라고 해 바로 다시 누르게 만들지만
 *   상한은 그동안 풀리지 않으므로 기다릴 분을 말한다. 분은 올림이다 — 내림이면 그 시각에 눌러도 다시 막힌다.
 *   상한 횟수는 말하지 않는다 — BE 상수를 손으로 옮기면 BE 가 바꿀 때 문구만 틀린 채 남는다.
 * - 503 `PUBLISH_SCREENING_UNAVAILABLE`: 심사 모델 호출이 실패한 것이지 작품이 거부된 것이 아니다. 바디에 `reason`
 *   이 없어 `getFilterRejectionReason` 이 고르지 않으므로 이의제기 진입점으로 가지 않는다.
 * - 409 `PUBLISH_CONFLICT`: 서버는 심사하는 동안 초안을 잡아 두지 않고, 다 끝난 뒤 초안이 아직 그대로인지 다시 본다.
 *   그사이 그림(대표 이미지·칸·상황 이미지)이 바뀌었거나 다른 창·두 번 누른 발행이 먼저 끝났으면 이 응답이다. 같은
 *   409 라도 칸 자리 충돌(`MEDIA_BOOK_CELL_POSITION_TAKEN`)처럼 code 가 다르면 고르지 않는다. */
export function getPublishFailureMessage(error: unknown): string | undefined {
  const rateLimit = getRateLimitDetail(error);
  if (rateLimit?.window === "publish") {
    const minutes = Math.max(1, Math.ceil(rateLimit.retryAfterSeconds / 60));
    return `발행 심사 요청이 너무 많았어요. 약 ${minutes}분 뒤에 다시 발행해 주세요.`;
  }
  if (!isApiError(error)) return undefined;
  if (error.status === 409) {
    return typeof error.detail === "object" && error.detail.code === PUBLISH_CONFLICT_CODE
      ? PUBLISH_CONFLICT_MESSAGE
      : undefined;
  }
  if (error.status !== 503) return undefined;
  if (typeof error.detail !== "object" || error.detail.code !== SCREENING_UNAVAILABLE_CODE) return undefined;
  const { message } = error.detail;
  return typeof message === "string" && message.length > 0 ? message : PUBLISH_SCREENING_UNAVAILABLE_MESSAGE;
}
