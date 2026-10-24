import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";

export type NovelSourceSelectionState = components["schemas"]["NovelSourceSelectionState"];
export type NovelSourceSelectionView = components["schemas"]["NovelSourceSelectionView"];
export type NovelSourceSelectionSaveRequest = components["schemas"]["NovelSourceSelectionSaveRequest"];

/** `GET /novels/{id}/source-selection` — 소설로 옮길 대화 구간 고르기의 상태(승인본·초안·기본 제안·이미 쓴 구간·지금 방 끝).
 * 구성 흐름 스위치가 꺼져 있으면 서버가 404 로 막고, 대화방이 지워진 소설은 409 다 — 그때는 호출부가 `enabled` 를 끈다. */
export function useNovelSourceSelectionQuery(novelId: string, options: { enabled: boolean }) {
  return useQuery<NovelSourceSelectionState, ApiError>({
    queryKey: novelKeys.sourceSelection(novelId),
    queryFn: async () => (await apiClient.get<NovelSourceSelectionState>(`/novels/${novelId}/source-selection`)).data,
    enabled: options.enabled,
  });
}

/** `PUT /novels/{id}/source-selection/draft` — 고른 구간을 새 초안으로 저장한다(무료). 응답이 상태 전체라 그것으로 캐시를 덮는다. */
export function useSaveNovelSourceSelectionMutation() {
  const queryClient = useQueryClient();
  return useMutation<NovelSourceSelectionState, ApiError, { novelId: string; body: NovelSourceSelectionSaveRequest }>({
    mutationFn: async ({ novelId, body }) =>
      (await apiClient.put<NovelSourceSelectionState>(`/novels/${novelId}/source-selection/draft`, body)).data,
    onSuccess: (state, { novelId }) => {
      queryClient.setQueryData(novelKeys.sourceSelection(novelId), state);
    },
  });
}

/** `POST /novels/{id}/source-selection/approve` — 최신 판을 승인한다(무료). 응답이 상태 전체라 그것으로 캐시를 덮는다. */
export function useApproveNovelSourceSelectionMutation() {
  const queryClient = useQueryClient();
  return useMutation<NovelSourceSelectionState, ApiError, { novelId: string; revision: number }>({
    mutationFn: async ({ novelId, revision }) =>
      (await apiClient.post<NovelSourceSelectionState>(`/novels/${novelId}/source-selection/approve`, { revision })).data,
    onSuccess: (state, { novelId }) => {
      queryClient.setQueryData(novelKeys.sourceSelection(novelId), state);
    },
  });
}
