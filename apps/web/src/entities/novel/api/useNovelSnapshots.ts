import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys, novelScoped } from "./keys";
import type { NovelDetailResponse } from "./useNovelQuery";

export type NovelSnapshotSummary = components["schemas"]["NovelSnapshotSummary"];
export type NovelSnapshotListResponse = components["schemas"]["NovelSnapshotListResponse"];
export type NovelSnapshotDetail = components["schemas"]["NovelSnapshotDetail"];
export type NovelSnapshotChapter = components["schemas"]["NovelSnapshotChapter"];
export type NovelSnapshotCharacter = components["schemas"]["NovelSnapshotCharacter"];
export type NovelSnapshotRestoreResponse = components["schemas"]["NovelSnapshotRestoreResponse"];

/** `GET /novels/{novelId}/snapshots` — 버전 목록(최근 것 먼저)과 소설당 상한. 내용은 상세 조회로 따로 읽는다. */
export function useNovelSnapshotsQuery(novelId: string) {
  return useQuery<NovelSnapshotListResponse, ApiError>({
    queryKey: novelKeys.snapshots(novelId),
    queryFn: async () => (await apiClient.get<NovelSnapshotListResponse>(`/novels/${novelId}/snapshots`)).data,
  });
}

/** `GET /novels/{novelId}/snapshots/{snapshotId}` — 버전 하나의 내용(화 본문은 없고 화마다 그때 개정 id). 같은 버전도
 * 마지막 묶음을 지우면 그 화 항목이 `deleted` 로 바뀌므로 판처럼 영원히 믿지 않는다. `snapshotId` 가 없으면 묻지
 * 않는다. */
export function useNovelSnapshotQuery(novelId: string, snapshotId: string | undefined) {
  return useQuery<NovelSnapshotDetail, ApiError>({
    queryKey: novelKeys.snapshot(novelId, snapshotId ?? ""),
    queryFn: async () =>
      (await apiClient.get<NovelSnapshotDetail>(`/novels/${novelId}/snapshots/${snapshotId ?? ""}`)).data,
    enabled: snapshotId !== undefined,
  });
}

/** `POST /novels/{novelId}/snapshots` — 지금 상태를 이름 붙여 남긴다(무과금). 상한에 닿으면 서버가 가장 오래된 자동
 * 저장부터 지우므로 목록 전체가 낡았다. 이름 붙인 것만으로 차 있으면 409 `NOVEL_SNAPSHOT_LIMIT`. */
export function useCreateNovelSnapshotMutation() {
  const queryClient = useQueryClient();
  return useMutation<NovelSnapshotSummary, ApiError, { novelId: string; name: string }>({
    mutationFn: async ({ novelId, name }) =>
      (await apiClient.post<NovelSnapshotSummary>(`/novels/${novelId}/snapshots`, { name })).data,
    onSuccess: (_, { novelId }) => {
      void queryClient.invalidateQueries({ queryKey: novelKeys.snapshots(novelId) });
    },
  });
}

/** `DELETE /novels/{novelId}/snapshots/{snapshotId}` — 버전 하나를 지운다(204). 그 버전의 내용 캐시는 **버린다** — 지운
 * 것을 다시 보여 줄 일이 없고, 남겨 두면 비교 화면이 지운 버전을 낡은 값으로 그린다. 목록은 낡았다. */
export function useDeleteNovelSnapshotMutation() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, { novelId: string; snapshotId: string }>({
    mutationFn: async ({ novelId, snapshotId }) => {
      await apiClient.delete(`/novels/${novelId}/snapshots/${snapshotId}`);
    },
    onSettled: (_, __, { novelId, snapshotId }) => {
      queryClient.removeQueries({ queryKey: novelKeys.snapshot(novelId, snapshotId) });
      void queryClient.invalidateQueries({ queryKey: novelKeys.snapshots(novelId) });
    },
  });
}

/** `POST /novels/{novelId}/snapshots/{snapshotId}/restore` — 그 버전 때의 내용으로 되돌린다(무과금). 응답의 상세로 상세
 * 캐시를 바로 덮고(화마다 새 개정 id 가 실려 본문 캐시 키가 저절로 바뀐다), 개정이 쌓인 화의 판 목록·인물 메모·버전
 * 목록(되돌리기 직전 자동 저장이 생긴다)·목록의 제목은 낡았다고 표시한다. 판 본문(`revision`)은 바뀌지 않아 그대로
 * 둔다. 진행 중 작업이 있으면 409 `NOVEL_JOB_IN_PROGRESS`. */
export function useRestoreNovelSnapshotMutation() {
  const queryClient = useQueryClient();
  return useMutation<NovelSnapshotRestoreResponse, ApiError, { novelId: string; snapshotId: string }>({
    mutationFn: async ({ novelId, snapshotId }) =>
      (await apiClient.post<NovelSnapshotRestoreResponse>(`/novels/${novelId}/snapshots/${snapshotId}/restore`)).data,
    onSuccess: ({ novel }, { novelId }) => {
      queryClient.setQueryData<NovelDetailResponse>(novelKeys.detail(novelId), novel);
      void queryClient.invalidateQueries({
        queryKey: novelKeys.all,
        predicate: novelScoped(novelId, ["chapter", "revisions", "characters", "snapshots", "snapshot"]),
      });
      void queryClient.invalidateQueries({ queryKey: novelKeys.list() });
    },
  });
}
