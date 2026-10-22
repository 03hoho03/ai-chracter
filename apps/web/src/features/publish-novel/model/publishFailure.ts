import { isApiError } from "@/shared/api/client";
import { getRateLimitDetail } from "@/shared/api/rateLimit";

/** 공개 요청 하나가 실패한 까닭.
 *
 * - `rejected`: 심사에 걸렸다(400). 걸린 화·글은 다시 받은 공개 상태의 마지막 심사가 말한다.
 * - `unavailable`: 심사를 지금 할 수 없었다(503) — 잠시 뒤 다시 하면 된다.
 * - `hourlyLimit`·`dailyLimit`: 심사 상한(429). 시간당 호출 상한은 다음 창에, 하루 거절 상한은 자정에 풀려 문장이
 *   다르다.
 * - `inReview`: 운영자가 첫 공개를 확인하고 있어 지금은 공개할 수 없다(409). 다시 시도해도 같으므로 다시 시도를 권하지
 *   않고, 공개 상태를 다시 받아 승인 대기를 그린다.
 * - `stale`: 화면이 낡았다(409 — 그사이 화가 바뀌었거나 다른 요청이 먼저 공개했거나, 원작·운영 상태가 바뀌었거나, 고른
 *   가격이 지금 상태와 맞지 않는다 — 무료로만 낼 수 있게 된 번호, 그사이 가격이 정해진 화). 공개 상태를 다시 받아 맞춘다.
 * - `salesStopped`: 운영자가 판매를 멈춰 새 화·다시 공개를 낼 수 없다(409). 다시 시도해도 같다.
 * - `summaryRequired`: 이미 공개한 화를 고쳐 다시 내는데 변경 요약이 없다(422). 화면이 낡아 요약 칸 없이 보낸 경우만
 *   닿는다 — 공개 모달을 다시 열면 칸이 나온다.
 * - `illustrationLimit`: 화에 붙은 삽화가 상한(10장)을 넘는다(409). 삽화를 줄여야 풀린다.
 * - `originalIllustration`: 원작자가 소설 공개를 허락하지 않은 원작의 그림이 화에 있다(409). 그 그림을 빼야 풀린다.
 * - `failed`: 그 밖(네트워크·5xx). */
export type PublishFailure =
  | { kind: "rejected" }
  | { kind: "unavailable" }
  | { kind: "hourlyLimit"; retryAfterSeconds: number }
  | { kind: "dailyLimit" }
  | { kind: "inReview" }
  | { kind: "stale" }
  | { kind: "salesStopped" }
  | { kind: "summaryRequired" }
  | { kind: "illustrationLimit" }
  | { kind: "originalIllustration" }
  | { kind: "failed" };

const STALE_CODES = new Set([
  "NOVEL_PUBLISH_CONFLICT",
  "NOVEL_PUBLISH_NOT_CONTIGUOUS",
  "NOVEL_SOURCE_NOT_PUBLISHABLE",
  "NOVEL_SOURCE_UNAVAILABLE",
  "NOVEL_PUBLICATION_RESTRICTED",
  "NOVEL_CHAPTER_NOT_FOUND",
  "NOVEL_CHAPTER_PRICE_LOCKED",
  "NOVEL_CHAPTER_ALREADY_PRICED",
]);

export function toPublishFailure(error: unknown): PublishFailure {
  const limit = getRateLimitDetail(error);
  if (limit?.window === "novel_screen_hourly") return { kind: "hourlyLimit", retryAfterSeconds: limit.retryAfterSeconds };
  if (limit?.window === "novel_screen_daily_reject") return { kind: "dailyLimit" };
  if (!isApiError(error)) return { kind: "failed" };
  const code = typeof error.detail === "object" && error.detail !== null ? error.detail.code : undefined;
  if (error.status === 400 && code === "NOVEL_SCREENING_REJECTED") return { kind: "rejected" };
  if (error.status === 503 && code === "NOVEL_SCREENING_UNAVAILABLE") return { kind: "unavailable" };
  if (error.status === 409 && code === "NOVEL_PUBLICATION_IN_REVIEW") return { kind: "inReview" };
  if (error.status === 409 && code === "NOVEL_PUBLICATION_SALES_STOPPED") return { kind: "salesStopped" };
  if (error.status === 422 && code === "NOVEL_CHANGE_SUMMARY_REQUIRED") return { kind: "summaryRequired" };
  if (error.status === 409 && code === "NOVEL_ILLUSTRATION_LIMIT_EXCEEDED") return { kind: "illustrationLimit" };
  if (error.status === 409 && code === "NOVEL_ILLUSTRATION_ORIGINAL_NOT_PUBLISHABLE") return { kind: "originalIllustration" };
  if (typeof code === "string" && STALE_CODES.has(code)) return { kind: "stale" };
  return { kind: "failed" };
}

/** 운영자가 내린 그림 때문에 걸린 심사 거절인가(400 에 `takenDownAssetIds` 가 실린다). 그러면 작가 화면의 화 본문을 다시
 * 받아야 그 그림 자리에 내린 그림 안내가 선다 — 그 화의 판은 그대로라 캐시 키가 같아 저절로는 다시 받지 않는다. 자산 id
 * 목록을 화면 상태로 들지 않는다: 다시 받은 응답이 같은 것을 말하고, 따로 들면 둘이 어긋날 길이 생긴다. */
export function hasTakenDownIllustrations(error: unknown): boolean {
  if (!isApiError(error) || typeof error.detail !== "object" || error.detail === null) return false;
  if (error.detail.code !== "NOVEL_SCREENING_REJECTED" || !("takenDownAssetIds" in error.detail)) return false;
  const { takenDownAssetIds } = error.detail;
  return Array.isArray(takenDownAssetIds) && takenDownAssetIds.length > 0;
}

/** 같은 요청을 다시 보내면 될 수 있는 실패인가 — "다시 시도" 버튼을 낼지. 심사 장애와 그 밖의 실패만이다. 승인 대기·
 * 낡음은 다시 받은 공개 상태가 할 일을 말하고, 거절·상한은 다시 보내도 같다. */
export function isRetryablePublishFailure(failure: PublishFailure): boolean {
  return failure.kind === "unavailable" || failure.kind === "failed";
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
    case "inReview":
      return "운영자가 첫 공개를 확인하고 있어 지금은 공개할 수 없어요. 확인이 끝나면 다시 공개할 수 있어요.";
    case "stale":
      return "그사이 소설이나 원작의 상태가 바뀌어 공개하지 못했어요. 바뀐 상태를 확인한 뒤 다시 시도해 주세요.";
    case "salesStopped":
      return "운영 정책에 따라 판매가 멈춰 공개하지 못했어요. 판매가 멈춘 동안은 새 화와 고친 내용을 공개할 수 없어요.";
    case "summaryRequired":
      return "고친 화를 다시 공개하려면 변경 요약이 필요해요. 다시 공개할 때 고친 화마다 바뀐 것을 적어 주세요.";
    case "illustrationLimit":
      return "한 화에는 삽화를 10장까지 넣을 수 있어요. 삽화를 줄인 뒤 다시 공개해 주세요.";
    case "originalIllustration":
      return "원작자가 소설 공개를 허락하지 않은 작품이라 원작 이미지가 든 화는 공개할 수 없어요. 원작 이미지를 뺀 뒤 다시 공개해 주세요.";
    case "failed":
      return "공개하지 못했어요. 잠시 후 다시 시도해 주세요.";
  }
}
