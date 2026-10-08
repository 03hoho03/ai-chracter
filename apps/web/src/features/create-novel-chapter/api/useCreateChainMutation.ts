import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { NovelChapterModelId, NovelJobResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

import { onNovelChapterJobStarted } from "./onNovelChapterJobStarted";

type CreateChainVariables = {
  novelId: string;
  model: NovelChapterModelId;
  /** 견적에서 고른 모델의 `cost` — 이용자가 본 금액. */
  expectedCost: number;
  /** 견적에서 고른 모델의 `batchCount`. 그사이 대화가 늘어도 이 수까지만 만든다. */
  maxBatches: number;
};

/** `POST /novels/{novelId}/chain` — "남은 대화 한 번에"(202 부모 작업). 모델은 연쇄 전체에 하나이고, 묶음마다 끝은
 * AI 가 정한다. 금액은 묶음 수 × 그 모델의 화 수 상한만큼 미리 받고 끝나면 쓰지 않은 몫을 돌려준다. 진행은 부모 작업의
 * `completedBatches`/`plannedBatches` 로 본다. 다른 화 작업처럼 시작 뒤 캐시 정리는 `onNovelChapterJobStarted` 가 한다
 * (잔액을 다시 받아야 해서 클로버 캐시를 아는 이 기능에 둔다). */
export function useCreateChainMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelJobResponse, ApiError, CreateChainVariables>({
    mutationFn: async ({ novelId, model, expectedCost, maxBatches }) =>
      (await apiClient.post<NovelJobResponse>(`/novels/${novelId}/chain`, { model, expectedCost, maxBatches })).data,
    onSuccess: (job, { novelId }) => onNovelChapterJobStarted(queryClient, novelId, job),
  });
}
