import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";
import type { NovelCharacterListResponse, NovelCharacterResponse } from "./useNovelCharactersQuery";

export type NovelCharacterUpdateRequest = components["schemas"]["NovelCharacterUpdateRequest"];

/** 인물 쓰기 셋은 모두 응답으로 카드 목록 전체를 돌려준다 — 그것으로 목록 캐시를 바로 덮는다. 다시 받게 두면 저장
 * 직후 옛 이름·메모가 한 번 칠해지고, 합치기 뒤에는 사라진 카드가 잠깐 남는다. 상세에는 인물이 없어 건드리지 않는다. */
function writeCharacters(queryClient: QueryClient, novelId: string, list: NovelCharacterListResponse) {
  queryClient.setQueryData<NovelCharacterResponse[]>(novelKeys.characters(novelId), list.items);
}

/** `PUT /novels/{novelId}/characters` — 생성이 아직 내지 않은 인물 카드를 직접 만든다. 같은 이름이 있으면 서버가
 * 아무것도 바꾸지 않는다(다시 보내도 같다). 다른 카드의 별칭이면 409 `NOVEL_CHARACTER_NAME_TAKEN`. */
export function useAddNovelCharacterMutation() {
  const queryClient = useQueryClient();
  return useMutation<NovelCharacterListResponse, ApiError, { novelId: string; name: string }>({
    mutationFn: async ({ novelId, name }) =>
      (await apiClient.put<NovelCharacterListResponse>(`/novels/${novelId}/characters`, { name })).data,
    onSuccess: (list, { novelId }) => writeCharacters(queryClient, novelId, list),
  });
}

/** `PATCH /novels/{novelId}/characters/{characterId}` — 이름·별칭·메모(보낸 칸만). 메모는 다음 묶음 생성 입력에 실린다.
 * 이름·별칭이 다른 카드와 겹치면 409 `NOVEL_CHARACTER_NAME_TAKEN` + `name`(겹친 값). */
export function useUpdateNovelCharacterMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    NovelCharacterListResponse,
    ApiError,
    { novelId: string; characterId: string; body: NovelCharacterUpdateRequest }
  >({
    mutationFn: async ({ novelId, characterId, body }) =>
      (await apiClient.patch<NovelCharacterListResponse>(`/novels/${novelId}/characters/${characterId}`, body)).data,
    onSuccess: (list, { novelId }) => writeCharacters(queryClient, novelId, list),
  });
}

/** `POST /novels/{novelId}/characters/{characterId}/merge` — 경로의 카드를 `intoCharacterId` 카드로 흡수한다. 이름·별칭은
 * 남는 카드의 별칭이 되고 메모는 그 뒤에 `[이름] 메모` 로 붙는다. 흡수된 카드의 보드 자리는 서버가 다음 배치 조회부터
 * 빼고 주므로 배치 캐시는 고치지 않는다(보드는 지금 있는 카드의 키만 다시 저장한다). */
export function useMergeNovelCharacterMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    NovelCharacterListResponse,
    ApiError,
    { novelId: string; characterId: string; intoCharacterId: string }
  >({
    mutationFn: async ({ novelId, characterId, intoCharacterId }) =>
      (
        await apiClient.post<NovelCharacterListResponse>(`/novels/${novelId}/characters/${characterId}/merge`, {
          intoCharacterId,
        })
      ).data,
    onSuccess: (list, { novelId }) => writeCharacters(queryClient, novelId, list),
  });
}
