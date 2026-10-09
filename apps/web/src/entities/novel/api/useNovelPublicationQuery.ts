import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";

export type NovelPublicationStatus = components["schemas"]["NovelPublicationStatusResponse"];
export type NovelPublicationScreening = components["schemas"]["NovelPublicationScreening"];

/** `GET /novels/{id}/publication` — 이 소설의 노벨 공개 상태(게시자만). 소설화를 쓸 수 없는 계정이나 노벨이 꺼져 있으면
 * 4xx 라 화면이 공개 자리를 그리지 않는다. 같은 응답이 다시 와도 결과가 같아 4xx 는 다시 묻지 않는다(전역 재시도
 * 기본값). */
export function useNovelPublicationQuery(novelId: string) {
  return useQuery<NovelPublicationStatus, ApiError>({
    queryKey: novelKeys.publication(novelId),
    queryFn: async () => (await apiClient.get<NovelPublicationStatus>(`/novels/${novelId}/publication`)).data,
  });
}
