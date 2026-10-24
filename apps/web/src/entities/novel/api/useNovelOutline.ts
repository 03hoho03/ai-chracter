import type { ApiError, components } from "@ai-character-chat/api-types";
import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";

export type NovelOutlineState = components["schemas"]["NovelOutlineState"];
export type NovelOutlineView = components["schemas"]["NovelOutlineView"];
export type NovelOutlineEpisode = components["schemas"]["NovelOutlineEpisodeView"];
export type NovelOutlineModel = components["schemas"]["NovelOutlineModel"];
/** 이 계정이 원고에 고를 수 있는 모델 하나와 그 턴(모델 응답) 수 상한. */
export type NovelChapterTurnCap = components["schemas"]["NovelChapterTurnCap"];
export type NovelOutlineSaveRequest = components["schemas"]["NovelOutlineSaveRequest"];
export type NovelOutlineEpisodeInput = components["schemas"]["NovelOutlineEpisodeInput"];

/** `GET /novels/{id}/outline` — 전체 구성안의 상태(승인본·초안·화 수 상한·고를 수 있는 모델과 구성안 금액). 화면의 조회와 구성안
 * 만들기 직전의 새로 받기가 같은 키·함수를 쓴다. 구성 흐름 스위치가 꺼져 있으면 서버가 404 로 막아 호출부가 부르지 않는다. */
export function novelOutlineQueryOptions(novelId: string) {
  return queryOptions<NovelOutlineState, ApiError>({
    queryKey: novelKeys.outline(novelId),
    queryFn: async () => (await apiClient.get<NovelOutlineState>(`/novels/${novelId}/outline`)).data,
  });
}

export function useNovelOutlineQuery(novelId: string, options: { enabled: boolean }) {
  return useQuery({ ...novelOutlineQueryOptions(novelId), enabled: options.enabled });
}

/** `PUT /novels/{id}/outline/draft` — 고친 구성안을 기준 판 위의 새 초안으로 저장한다(무료). 응답이 상태 전체라 그것으로 캐시를 덮는다. */
export function useSaveNovelOutlineMutation() {
  const queryClient = useQueryClient();
  return useMutation<NovelOutlineState, ApiError, { novelId: string; body: NovelOutlineSaveRequest }>({
    mutationFn: async ({ novelId, body }) =>
      (await apiClient.put<NovelOutlineState>(`/novels/${novelId}/outline/draft`, body)).data,
    onSuccess: (state, { novelId }) => {
      queryClient.setQueryData(novelKeys.outline(novelId), state);
      // 화마다의 근거가 바뀌면 그 화 장면 구성안의 낡음 표시가 바뀐다.
      void queryClient.invalidateQueries({ queryKey: novelKeys.episodeOutlineAll(novelId) });
    },
  });
}

/** `POST /novels/{id}/outline/approve` — 가장 최근 판을 승인한다(무료). 응답이 상태 전체라 그것으로 캐시를 덮는다. */
export function useApproveNovelOutlineMutation() {
  const queryClient = useQueryClient();
  return useMutation<NovelOutlineState, ApiError, { novelId: string; revision: number }>({
    mutationFn: async ({ novelId, revision }) =>
      (await apiClient.post<NovelOutlineState>(`/novels/${novelId}/outline/approve`, { revision })).data,
    onSuccess: (state, { novelId }) => {
      queryClient.setQueryData(novelKeys.outline(novelId), state);
      // 화마다의 근거가 바뀌면 그 화 장면 구성안의 낡음 표시가 바뀐다.
      void queryClient.invalidateQueries({ queryKey: novelKeys.episodeOutlineAll(novelId) });
    },
  });
}
