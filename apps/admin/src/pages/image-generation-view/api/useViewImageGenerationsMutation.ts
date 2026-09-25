import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminUserKeys } from "@/entities/admin-user";
import { apiClient } from "@/shared/lib/api/client";

export type AdminImageGenerationViewRequest = components["schemas"]["AdminImageGenerationViewRequest"];
export type AdminImageGenerationDetailListResponse = components["schemas"]["AdminImageGenerationDetailListResponse"];
export type AdminImageGenerationDetailItem = components["schemas"]["AdminImageGenerationDetailItem"];
export type AdminImageGenerationImageItem = components["schemas"]["AdminImageGenerationImageItem"];

/** `useViewChatMutation` 동형 — 이 훅의 호출 1회 = 서버
 * 감사 로그 1행. 결과를 쿼리 캐시에 남기지 않는다(그 순간의 열람 결과일 뿐 재사용할 서버 상태가
 * 아니다). 페이지 누적(더보기와의 합산)은 호출부(`ImageGenerationViewPage`)의 로컬 state가 맡는다.
 *
 * 성공 시 유저 쿼리를 무효화한다 — 이 POST가 만든 감사 로그 행이 유저 상세의 "조치 이력" 표에
 * "이미지 열람"으로 나오기 때문. */
export function useViewImageGenerationsMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminImageGenerationDetailListResponse, ApiError, AdminImageGenerationViewRequest>({
    mutationFn: async (payload) =>
      (
        await apiClient.post<AdminImageGenerationDetailListResponse>(
          `/admin/users/${userId}/image-generations/view`,
          payload,
        )
      ).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
