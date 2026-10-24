import type { ApiError, components } from "@ai-character-chat/api-types";
import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";

export type NovelEpisodeOutlineState = components["schemas"]["NovelEpisodeOutlineState"];
export type NovelEpisodeOutlineView = components["schemas"]["NovelEpisodeOutlineView"];
export type NovelSceneView = components["schemas"]["NovelSceneView"];
export type NovelSceneInput = components["schemas"]["NovelSceneInput"];
export type NovelEpisodeOutlineSaveRequest = components["schemas"]["NovelEpisodeOutlineSaveRequest"];

/** `GET /novels/{id}/outline/episodes/{key}/scenes` — 한 화의 장면 구성안 상태(승인본·초안·장면 구성안 금액·원고 금액·이미 쓴 화). 화면의
 * 조회와 만들기·원고 직전의 새로 받기가 같은 키·함수를 쓴다. 구성 흐름 스위치가 꺼져 있으면 서버가 404 로 막아 호출부가 부르지 않는다. */
export function novelEpisodeOutlineQueryOptions(novelId: string, episodeKey: string) {
  return queryOptions<NovelEpisodeOutlineState, ApiError>({
    queryKey: novelKeys.episodeOutline(novelId, episodeKey),
    queryFn: async () =>
      (await apiClient.get<NovelEpisodeOutlineState>(`/novels/${novelId}/outline/episodes/${episodeKey}/scenes`)).data,
  });
}

export function useNovelEpisodeOutlineQuery(novelId: string, episodeKey: string, options: { enabled: boolean }) {
  return useQuery({ ...novelEpisodeOutlineQueryOptions(novelId, episodeKey), enabled: options.enabled });
}

/** 장면 구성안 저장·승인 뒤의 캐시 — 응답이 그 화 상태 전체라 그것으로 덮고, 전체 구성안의 화마다 상태(`sceneOutline`)는 다시 받는다. */
function useOnEpisodeOutlineState() {
  const queryClient = useQueryClient();
  return (state: NovelEpisodeOutlineState, novelId: string) => {
    queryClient.setQueryData(novelKeys.episodeOutline(novelId, state.episodeKey), state);
    void queryClient.invalidateQueries({ queryKey: novelKeys.outline(novelId) });
  };
}

/** `PUT …/scenes/draft` — 고친 장면 구성안을 기준 판 위의 새 초안으로 저장한다(무료). */
export function useSaveNovelEpisodeOutlineMutation() {
  const onState = useOnEpisodeOutlineState();
  return useMutation<
    NovelEpisodeOutlineState,
    ApiError,
    { novelId: string; episodeKey: string; body: NovelEpisodeOutlineSaveRequest }
  >({
    mutationFn: async ({ novelId, episodeKey, body }) =>
      (await apiClient.put<NovelEpisodeOutlineState>(`/novels/${novelId}/outline/episodes/${episodeKey}/scenes/draft`, body))
        .data,
    onSuccess: (state, { novelId }) => onState(state, novelId),
  });
}

/** `POST …/scenes/approve` — 그 화의 가장 최근 판을 승인한다(무료). */
export function useApproveNovelEpisodeOutlineMutation() {
  const onState = useOnEpisodeOutlineState();
  return useMutation<NovelEpisodeOutlineState, ApiError, { novelId: string; episodeKey: string; revision: number }>({
    mutationFn: async ({ novelId, episodeKey, revision }) =>
      (
        await apiClient.post<NovelEpisodeOutlineState>(`/novels/${novelId}/outline/episodes/${episodeKey}/scenes/approve`, {
          revision,
        })
      ).data,
    onSuccess: (state, { novelId }) => onState(state, novelId),
  });
}
