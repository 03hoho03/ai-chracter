import { isApiError } from "@/shared/api/client";

/** "무료로 전환"이 실패한 까닭.
 *
 * - `stale`: 화면이 낡았다 — 그 화가 더는 공개한 화가 아니거나(404, 지웠거나 거두기로 바뀜), 노벨 정책 스위치가 그사이
 *   꺼져 화마다 가격을 바꿀 수 없다(409). 공개 상태를 다시 받아 맞춘다.
 * - `failed`: 그 밖(네트워크·5xx). 같은 요청을 다시 보내면 될 수 있다. */
export type MakeChapterFreeFailure = "stale" | "failed";

const STALE_CODES = new Set(["NOVEL_CHAPTER_NOT_FOUND", "NOVEL_PRICE_CHOICE_DISABLED"]);

export function toMakeChapterFreeFailure(error: unknown): MakeChapterFreeFailure {
  if (!isApiError(error)) return "failed";
  const code = typeof error.detail === "object" && error.detail !== null ? error.detail.code : undefined;
  return typeof code === "string" && STALE_CODES.has(code) ? "stale" : "failed";
}

export const MAKE_CHAPTER_FREE_FAILURE_MESSAGES: Record<MakeChapterFreeFailure, string> = {
  stale: "그사이 소설의 상태가 바뀌어 무료로 바꾸지 못했어요. 바뀐 상태를 확인해 주세요.",
  failed: "무료로 바꾸지 못했어요. 잠시 후 다시 시도해 주세요.",
};
