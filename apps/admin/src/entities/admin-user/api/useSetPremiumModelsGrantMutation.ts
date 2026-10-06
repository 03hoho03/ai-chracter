import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminUserFeatureGrantRequest = components["schemas"]["AdminUserFeatureGrantRequest"];

/** 상위 글쓰기 모델 허용은 채팅과 소설화가 따로다 — 같은 계정에 하나만 줄 수 있다. */
export type PremiumModelsGrantScope = "chat" | "novelize";

const GRANT_PATH: Record<PremiumModelsGrantScope, string> = {
  chat: "chat-premium-models-grant",
  novelize: "novelize-premium-models-grant",
};

type SetPremiumModelsGrantVariables = AdminUserFeatureGrantRequest & { scope: PremiumModelsGrantScope };

/** POST /admin/users/{id}/{chat|novelize}-premium-models-grant — 응답 204(본문 없음). 소설화 허용 토글과 같은 모양이다:
 * `granted` 한 필드로 허용·회수하고, 공백 `adminComment`는 BE가 422로 거부하며(호출부 스키마가 먼저 막는다), 허용은 서버 env
 * 명단 안의 계정에만 된다 — 명단 밖이면 422 `detail.code`가 `CHAT_PREMIUM_MODELS_GRANT_NOT_ALLOWLISTED`·
 * `NOVELIZE_PREMIUM_MODELS_GRANT_NOT_ALLOWLISTED`다(OpenAPI에 없어 호출부가 문자열로 가른다). 두 경로가 요청·응답 모양이 같아
 * 훅 하나가 `scope`로 경로만 고른다. 상세 응답의 허용 시각이 바뀌므로 유저 쿼리 전체를 끊는다. */
export function useSetPremiumModelsGrantMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, SetPremiumModelsGrantVariables>({
    mutationFn: async ({ scope, ...payload }) => {
      await apiClient.post(`/admin/users/${userId}/${GRANT_PATH[scope]}`, payload);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
