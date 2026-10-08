import type { components } from "@ai-character-chat/api-types";

import { apiClient } from "@/shared/api/client";
import { keepaliveFetch } from "@/shared/api/keepaliveFetch";

export type NovelReadingPositionRequest = components["schemas"]["NovelReadingPositionRequest"];

function readingPositionPath(novelId: string, chapterId: string): string {
  return `/novels/${novelId}/chapters/${chapterId}/reading-position`;
}

/** `PUT /novels/{novelId}/chapters/{chapterId}/reading-position` — 화를 읽던 자리(204, 같은 값을 다시 보내도 같다).
 * 읽는 동안의 저장이라 실패를 알리지 않는다 — 다음 저장이 같은 자리를 다시 덮는다. 응답 본문이 없어 상세 캐시의
 * 이어 읽기·읽음 표시는 이걸로 고쳐지지 않는다(읽기 화면을 떠날 때 상세를 다시 받는다). */
export async function saveReadingPosition(
  novelId: string,
  chapterId: string,
  body: NovelReadingPositionRequest,
): Promise<void> {
  try {
    await apiClient.put(readingPositionPath(novelId, chapterId), body);
  } catch {
    // 읽은 자리는 최선 노력이다. 세션·재동의 같은 전역 실패는 다음 화면 이동이 따로 알린다.
  }
}

/** 같은 저장을 페이지가 숨거나 닫히는 순간에 보낸다. 그때는 axios 요청이 끊기므로 `keepalive` fetch 로 보낸다. */
export function sendReadingPositionKeepalive(
  novelId: string,
  chapterId: string,
  body: NovelReadingPositionRequest,
): Promise<void> {
  return keepaliveFetch("PUT", readingPositionPath(novelId, chapterId), body);
}
