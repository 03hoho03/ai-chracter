import { isApiError } from "@/shared/api/client";
import { getRateLimitDetail } from "@/shared/api/rateLimit";

/** 공개 요청 하나가 실패한 까닭.
 *
 * - `rejected`: 심사에 걸렸다(400). 걸린 화·글은 다시 받은 공개 상태의 마지막 심사가 말한다.
 * - `unavailable`: 심사를 지금 할 수 없었다(503) — 잠시 뒤 다시 하면 된다.
 * - `hourlyLimit`·`dailyLimit`: 심사 상한(429). 시간당 호출 상한은 다음 창에, 하루 거절 상한은 자정에 풀려 문장이
 *   다르다.
 * - `stale`: 화면이 낡았다(409 — 그사이 화가 바뀌었거나 다른 요청이 먼저 공개했거나, 원작·운영 상태가 바뀌었다). 공개
 *   상태를 다시 받아 맞춘다.
 * - `failed`: 그 밖(네트워크·5xx). */
export type PublishFailure =
  | { kind: "rejected" }
  | { kind: "unavailable" }
  | { kind: "hourlyLimit"; retryAfterSeconds: number }
  | { kind: "dailyLimit" }
  | { kind: "stale" }
  | { kind: "failed" };

const STALE_CODES = new Set([
  "NOVEL_PUBLISH_CONFLICT",
  "NOVEL_PUBLISH_NOT_CONTIGUOUS",
  "NOVEL_SOURCE_NOT_PUBLISHABLE",
  "NOVEL_SOURCE_UNAVAILABLE",
  "NOVEL_PUBLICATION_RESTRICTED",
  "NOVEL_CHAPTER_NOT_FOUND",
]);

export function toPublishFailure(error: unknown): PublishFailure {
  const limit = getRateLimitDetail(error);
  if (limit?.window === "novel_screen_hourly") return { kind: "hourlyLimit", retryAfterSeconds: limit.retryAfterSeconds };
  if (limit?.window === "novel_screen_daily_reject") return { kind: "dailyLimit" };
  if (!isApiError(error)) return { kind: "failed" };
  const code = typeof error.detail === "object" && error.detail !== null ? error.detail.code : undefined;
  if (error.status === 400 && code === "NOVEL_SCREENING_REJECTED") return { kind: "rejected" };
  if (error.status === 503 && code === "NOVEL_SCREENING_UNAVAILABLE") return { kind: "unavailable" };
  if (typeof code === "string" && STALE_CODES.has(code)) return { kind: "stale" };
  return { kind: "failed" };
}

/** 실패 문장. 심사 거절은 공개 상태의 마지막 심사로 따로 말하므로 여기서는 없다(`undefined`). */
export function toPublishFailureMessage(failure: PublishFailure): string | undefined {
  switch (failure.kind) {
    case "rejected":
      return undefined;
    case "unavailable":
      return "지금은 내용을 확인할 수 없어 공개하지 못했어요. 잠시 후 다시 시도해 주세요.";
    case "hourlyLimit":
      return `공개 확인을 짧은 시간에 많이 했어요. ${Math.max(Math.ceil(failure.retryAfterSeconds / 60), 1)}분 뒤 다시 시도해 주세요.`;
    case "dailyLimit":
      return "오늘은 공개 확인에 걸린 횟수가 많아 더 시도할 수 없어요. 내일 다시 시도해 주세요.";
    case "stale":
      return "그사이 소설이나 원작의 상태가 바뀌어 공개하지 못했어요. 바뀐 상태를 확인한 뒤 다시 시도해 주세요.";
    case "failed":
      return "공개하지 못했어요. 잠시 후 다시 시도해 주세요.";
  }
}
