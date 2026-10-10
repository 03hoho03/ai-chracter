import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminUserFeatureGrantRequest = components["schemas"]["AdminUserFeatureGrantRequest"];

/** POST /admin/users/{id}/novelize-premium-models-grant — 소설 장 생성의 상위 글쓰기 모델 허용. 응답 204(본문 없음). 소설화
 * 허용 토글과 같은 모양이다: `granted` 한 필드로 허용·회수하고, 공백 `adminComment`는 BE가 422로 거부하며(호출부 스키마가 먼저
 * 막는다), 허용은 서버 env 명단 안의 계정에만 된다 — 명단 밖이면 422 `detail.code`가 `NOVELIZE_PREMIUM_MODELS_GRANT_NOT_ALLOWLISTED`다
 * (OpenAPI에 없어 호출부가 문자열로 가른다). 채팅 상위 모델은 서버 스위치 하나로 모든 회원에게 열려 계정별 허용이 없다. 상세
 * 응답의 허용 시각이 바뀌므로 유저 쿼리 전체를 끊는다. */
export function useSetPremiumModelsGrantMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, AdminUserFeatureGrantRequest>({
    mutationFn: async (payload) => {
      await apiClient.post(`/admin/users/${userId}/novelize-premium-models-grant`, payload);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
