import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { noticeKeys } from "./keys";
import type { AdminNoticeDetailResponse } from "./useNoticeDetailQuery";

export type AdminNoticeCreateRequest = components["schemas"]["AdminNoticeCreateRequest"];

/** 생성은 `published=false`로 시작한다(BE).
 *
 * 성공 시 **응답으로 상세 캐시를 먼저 채우고** 목록을 무효화한다(`apps/web/CLAUDE.md` — 쿼리 키가
 * 바뀌는 URL 교체는 `setQueryData` 뒤에 navigate). 안 채우면 `/notices/new` → `/notices/$id` 교체
 * 직후 상세 쿼리가 빈 캐시에서 시작해 **스켈레톤이 한 번 깜빡인 뒤** 에디터가 리마운트된다.
 * 뒤따르는 무효화가 방금 넣은 값을 지우지는 않는다 — 이 시점의 상세 쿼리에는 아직 관찰자가 없어
 * stale 표시만 되고(기본 `refetchType: "active"`), navigate 후 데이터를 즉시 서빙하면서
 * 백그라운드로만 갱신된다. */
export function useCreateNoticeMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminNoticeDetailResponse, ApiError, AdminNoticeCreateRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminNoticeDetailResponse>("/admin/notices", payload)).data,
    onSuccess: (created) => {
      queryClient.setQueryData(noticeKeys.detail(created.id), created);
      return queryClient.invalidateQueries({ queryKey: noticeKeys.all });
    },
  });
}
