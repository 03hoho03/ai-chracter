import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  novelKeys,
  withSettledPatches,
  writeNovelChapterRevision,
  type NovelChapterResponse,
  type NovelDetailResponse,
} from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

import type { PatchUnitRequest } from "../model/blockEditPatches";

type ApplyPatchUnitVariables = {
  novelId: string;
  jobId: string;
  unit: PatchUnitRequest;
  /** 단위에 든 수정안 id — 응답에는 어느 수정안을 적용했는지가 없어 캐시를 고치는 데 쓴다. */
  patchIds: readonly string[];
};

/** `POST /novels/{novelId}/jobs/{jobId}/patches/apply` — 적용 단위(독립 수정안 하나·묶음 하나)를 새 개정 하나로 쌓는다(201, 무과금).
 * 캐시는 장 쓰기 규칙을 그대로 쓰되, 여러 문단 수정안은 화 단위로 빼지 않고 적용한 수정안만 적용으로 바꾼다. 같은 화의 다른
 * 수정안이 그 개정으로 쓸 수 없게 됐는지는 다시 받은 상세가 알려 준다. */
export function useApplyPatchUnitMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelChapterResponse, ApiError, ApplyPatchUnitVariables>({
    mutationFn: async ({ novelId, jobId, unit }) =>
      (await apiClient.post<NovelChapterResponse>(`/novels/${novelId}/jobs/${jobId}/patches/apply`, unit)).data,
    onSuccess: (chapter, { jobId, patchIds }) =>
      writeNovelChapterRevision(queryClient, chapter, { appliedPatches: { jobId, patchIds } }),
  });
}

type DismissPatchUnitVariables = {
  novelId: string;
  jobId: string;
  /** 버릴 단위, 또는 그 작업의 남은 수정안 전부(`"all"`). */
  unit: PatchUnitRequest | "all";
  patchIds: readonly string[] | "all";
};

/** `POST /novels/{novelId}/jobs/{jobId}/patches/dismiss` — 수정안을 적용하지 않고 버린다(204, 환불 없음). 응답에 본문이 없어 상세의
 * 그 수정안을 바로 버림으로 바꾸고(대기가 없어진 작업은 빠진다) 서버 값으로 다시 받게 표시한다. */
export function useDismissPatchUnitMutation() {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, DismissPatchUnitVariables>({
    mutationFn: async ({ novelId, jobId, unit }) => {
      await apiClient.post(`/novels/${novelId}/jobs/${jobId}/patches/dismiss`, unit === "all" ? { all: true } : unit);
    },
    onSuccess: (_, { novelId, jobId, patchIds }) => {
      queryClient.setQueryData<NovelDetailResponse>(novelKeys.detail(novelId), (novel) =>
        novel === undefined
          ? undefined
          : { ...novel, pendingBlockEdits: withSettledPatches(novel.pendingBlockEdits, jobId, patchIds, "dismissed") },
      );
      void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
    },
  });
}
