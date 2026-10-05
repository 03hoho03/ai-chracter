import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";

export type NovelDetailResponse = components["schemas"]["NovelDetailResponse"];
export type NovelChapterSummary = components["schemas"]["NovelChapterSummary"];

/** `GET /novels/{id}` — 소설 상세(장 목차·진행 중 작업·단가·입력 상한). 단가와 상한은 이 응답에서만 읽고 화면에
 * 사본을 두지 않는다 — 서버가 값을 바꾸면 사본이 조용히 어긋난다.
 *
 * 채팅방 캐시(`chatRoomKeys.detail`)는 읽지도 쓰지도 않는다. 그 캐시는 최근 메시지 한 페이지만 들고 있고, 앞
 * 페이지를 이어 붙이는 로직이 "캐시 첫 메시지가 커서"라는 전제에 기대므로 다른 화면이 손대면 불러온 페이지를
 * 버리게 된다. */
export function useNovelQuery(novelId: string) {
  return useQuery<NovelDetailResponse, ApiError>({
    queryKey: novelKeys.detail(novelId),
    queryFn: async () => (await apiClient.get<NovelDetailResponse>(`/novels/${novelId}`)).data,
  });
}
