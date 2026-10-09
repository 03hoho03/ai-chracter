import type { components } from "@ai-character-chat/api-types";

import { apiClient } from "@/shared/api/client";
import { keepaliveFetch } from "@/shared/api/keepaliveFetch";

export type WebnovelReadingPositionRequest = components["schemas"]["PublicNovelReadingPositionRequest"];

function readingPositionPath(novelId: string, chapterId: string): string {
  return `/webnovels/${novelId}/chapters/${chapterId}/reading-position`;
}

/** `PUT /webnovels/{novelId}/chapters/{chapterId}/reading-position` — 노벨 화를 읽던 자리(204). 소유자 소설의 읽은
 * 자리 저장과 같은 최선 노력이라 실패를 알리지 않는다 — 다음 저장이 같은 자리를 다시 덮는다. */
export async function saveWebnovelReadingPosition(
  novelId: string,
  chapterId: string,
  body: WebnovelReadingPositionRequest,
): Promise<void> {
  try {
    await apiClient.put(readingPositionPath(novelId, chapterId), body);
  } catch {
    // 읽은 자리는 최선 노력이다. 세션·재동의 같은 전역 실패는 다음 화면 이동이 따로 알린다.
  }
}

/** 같은 저장을 페이지가 숨거나 닫히는 순간에 보낸다(그때는 axios 요청이 끊긴다). */
export function sendWebnovelReadingPositionKeepalive(
  novelId: string,
  chapterId: string,
  body: WebnovelReadingPositionRequest,
): Promise<void> {
  return keepaliveFetch("PUT", readingPositionPath(novelId, chapterId), body);
}
