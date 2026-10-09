import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys } from "./keys";

export type AdminNovelModerationRequest = components["schemas"]["AdminNovelModerationRequest"];
export type NovelModerationAction = AdminNovelModerationRequest["action"];
type AdminNovelModerationResponse = components["schemas"]["AdminNovelModerationResponse"];

/** 노벨 이용제한·해제. 사유는 필수(공백뿐이면 422)이고, 이미 그 상태면 409 다. 끝나면(409 포함) 노벨 쿼리 전체를
 * 무효화한다 — 목록·상세·홈 노벨 현황이 모두 이용제한 여부를 보이고, 409 는 다른 운영자가 먼저 바꿨다는 뜻이다. */
export function useNovelModerationMutation(novelId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminNovelModerationResponse, ApiError, AdminNovelModerationRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminNovelModerationResponse>(`/admin/novels/${novelId}/moderation`, payload)).data,
    onSettled: () => queryClient.invalidateQueries({ queryKey: adminNovelKeys.all }),
  });
}
