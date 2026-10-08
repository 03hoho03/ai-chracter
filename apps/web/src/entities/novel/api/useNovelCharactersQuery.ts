import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";

export type NovelCharacterResponse = components["schemas"]["NovelCharacterResponse"];
export type NovelCharacterListResponse = components["schemas"]["NovelCharacterListResponse"];

/** `GET /novels/{novelId}/characters` — 인물 카드(만든 순서)와 카드마다 나온 화. 상세에 싣지 않고 따로 받는다 — 인물을
 * 쓰는 화면은 편집 보드뿐이라 읽기 화면·작품 정보가 그 무게를 지지 않게. 생성이 끝나면(`novelKeys.all` 무효화) 새
 * 인물이 붙어 다시 받는다. */
export function useNovelCharactersQuery(novelId: string) {
  return useQuery<NovelCharacterResponse[], ApiError>({
    queryKey: novelKeys.characters(novelId),
    queryFn: async () =>
      (await apiClient.get<NovelCharacterListResponse>(`/novels/${novelId}/characters`)).data.items,
  });
}
