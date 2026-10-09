import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { webnovelKeys } from "./keys";

export type WebnovelDetailResponse = components["schemas"]["PublicNovelDetailResponse"];
export type WebnovelChapterItem = components["schemas"]["PublicNovelChapterItem"];
export type WebnovelChapterAccess = WebnovelChapterItem["access"];
export type WebnovelReadingPosition = components["schemas"]["PublicNovelReadingPosition"];

/** `GET /webnovels/{novelId}` — 노벨 작품 정보와 목차(화마다 이 사람에게의 상태·가격·읽던 자리). 읽을 수 없으면
 * 소장했던 사람에게 410(열람 종료와 이유), 아니면 404 다(`toWebnovelLoadFailure`). 같은 응답이 다시 와도 결과가
 * 같아 4xx 는 다시 묻지 않는다(전역 재시도 기본값). 공개 중일 때만 물을 자리(게시자가 내 소설 화면에서 보는 좋아요·조회
 * 수)는 `enabled` 로 끈다. */
export function useWebnovelQuery(novelId: string, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery<WebnovelDetailResponse, ApiError>({
    enabled,
    queryKey: webnovelKeys.detail(novelId),
    queryFn: async () => (await apiClient.get<WebnovelDetailResponse>(`/webnovels/${novelId}`)).data,
  });
}
