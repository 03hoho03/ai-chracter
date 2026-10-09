import { isApiError } from "@/shared/api/client";

/** 소장한 사람이 더는 읽을 수 없게 된 이유(서버 410 `NOVEL_READING_ENDED` 의 `reason`). 서버가 앞의 것부터 고른다. */
export const WEBNOVEL_ENDED_REASONS = [
  "deleted",
  "publisher_withdrawn",
  "withdrawn",
  "restricted",
  "source_unavailable",
  "service_off",
] as const;
export type WebnovelEndedReason = (typeof WEBNOVEL_ENDED_REASONS)[number];

/** 노벨 작품 정보·화를 못 읽었을 때 화면이 그릴 것.
 *
 * - `ended`: 이 소설을 소장했던 사람에게만 오는 열람 종료(이유와, 게시자가 지워 돌려준 클로버). 이유가 이 화면이 모르는
 *   값이면 `reason` 이 없다(서버가 이유를 늘린 뒤 옛 화면이 받는 구간) — 그때는 이유 없이 볼 수 없다고만 말한다.
 * - `missing`: 없거나 지금 읽을 수 없는 소설·화. 소장하지 않은 사람에게는 이유를 가르지 않는다(게시자의 철회·운영
 *   조치를 제3자에게 알릴 까닭이 없다) — 노벨이 꺼져 있을 때도 같다.
 * - `failed`: 네트워크·5xx — 다시 시도할 수 있다. */
export type WebnovelLoadFailure =
  | { kind: "ended"; reason: WebnovelEndedReason | undefined; refundedAmount: number }
  | { kind: "missing" }
  | { kind: "failed" };

function isEndedReason(value: unknown): value is WebnovelEndedReason {
  return WEBNOVEL_ENDED_REASONS.some((reason) => reason === value);
}

export function toWebnovelLoadFailure(error: unknown): WebnovelLoadFailure {
  if (!isApiError(error)) return { kind: "failed" };
  if (error.status === 404) return { kind: "missing" };
  const detail = typeof error.detail === "object" && error.detail !== null ? error.detail : undefined;
  if (error.status === 410 && detail?.code === "NOVEL_READING_ENDED") {
    const { reason, refundedAmount } = detail;
    return {
      kind: "ended",
      reason: isEndedReason(reason) ? reason : undefined,
      refundedAmount: typeof refundedAmount === "number" ? refundedAmount : 0,
    };
  }
  return { kind: "failed" };
}
