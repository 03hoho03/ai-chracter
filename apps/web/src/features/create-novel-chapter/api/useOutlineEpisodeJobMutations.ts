import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { NovelChapterModelId, NovelJobResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

import { onNovelChapterJobStarted } from "./onNovelChapterJobStarted";

type EpisodeJobVariables = { novelId: string; episodeKey: string; expectedCost: number; model: NovelChapterModelId };
type OutlineRegenerateVariables = { novelId: string; chapterId: string; expectedCost: number; model: NovelChapterModelId };

/** `POST /novels/{novelId}/outline/episodes/{key}/scenes` — 지금 승인한 전체 구성안의 그 화로 장면 구성안을 만드는 작업(202). 금액은 고른
 * 모델의 장면 구성안 고정가이고 `expectedCost` 는 장면 구성안 조회의 그 모델 금액이다. 끝나면 새 장면 구성안이 미승인 초안으로 온다. */
export function useCreateEpisodeOutlineMutation() {
  const queryClient = useQueryClient();
  return useMutation<NovelJobResponse, ApiError, EpisodeJobVariables>({
    mutationFn: async ({ novelId, episodeKey, expectedCost, model }) =>
      (
        await apiClient.post<NovelJobResponse>(`/novels/${novelId}/outline/episodes/${episodeKey}/scenes`, {
          expectedCost,
          model,
        })
      ).data,
    onSuccess: (job, { novelId }) => onNovelChapterJobStarted(queryClient, novelId, job),
  });
}

/** `POST /novels/{novelId}/outline/episodes/{key}/chapter` — 그 화의 승인한 장면 구성안으로 원고(화 하나)를 쓰는 작업(202). 금액은 고른
 * 모델의 화 단가 하나이고 `expectedCost` 는 장면 구성안 조회의 원고 금액(`chapterModels`)이다. 끝나면 다음 화 번호의 새 화가 생긴다. */
export function useCreateOutlineChapterMutation() {
  const queryClient = useQueryClient();
  return useMutation<NovelJobResponse, ApiError, EpisodeJobVariables>({
    mutationFn: async ({ novelId, episodeKey, expectedCost, model }) =>
      (
        await apiClient.post<NovelJobResponse>(`/novels/${novelId}/outline/episodes/${episodeKey}/chapter`, {
          expectedCost,
          model,
        })
      ).data,
    onSuccess: (job, { novelId }) => onNovelChapterJobStarted(queryClient, novelId, job),
  });
}

/** `POST /novels/{novelId}/outline/chapters/{chapterId}/regenerate` — 구성안으로 쓴 화 하나를 같은 장면 구성안으로 다시 쓰는 작업(202).
 * 결과는 그 화의 새 개정이라 지금 글은 이력에 남는다. 금액은 고른 모델의 화 단가로, 상세의 그 화 묶음 다시 만들기 목록과 같다. */
export function useRegenerateOutlineChapterMutation() {
  const queryClient = useQueryClient();
  return useMutation<NovelJobResponse, ApiError, OutlineRegenerateVariables>({
    mutationFn: async ({ novelId, chapterId, expectedCost, model }) =>
      (
        await apiClient.post<NovelJobResponse>(`/novels/${novelId}/outline/chapters/${chapterId}/regenerate`, {
          expectedCost,
          model,
        })
      ).data,
    onSuccess: (job, { novelId }) => onNovelChapterJobStarted(queryClient, novelId, job),
  });
}
