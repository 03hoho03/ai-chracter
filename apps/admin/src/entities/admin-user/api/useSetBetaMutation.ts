import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminUserBetaRequest = components["schemas"]["AdminUserBetaRequest"];

/** POST /admin/users/{id}/beta — 응답 204(본문 없음). 레이트리밋 면제 토글과 같은 모양으로
 * 지정·해제를 `beta` 한 필드로 받는다. `adminComment`는 스키마상 optional이지만 공백이면 BE가
 * 422를 내 사실상 필수다 — 호출부(UserActionConfirmModal)가 스키마로 빈 값을 막는다.
 * 지정 시 만 19세 미만(또는 생년월일 없음)이면 BE가 422 `detail.code === "BETA_AGE_RESTRICTED"`로
 * 거부한다. 그 code는 OpenAPI에 나오지 않아 호출부가 문자열로 가른다.
 * `all`을 끊는 이유: 상세의 지정 시각과 목록의 베타 표시·"베타만" 필터 결과가 함께 바뀐다. */
export function useSetBetaMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, AdminUserBetaRequest>({
    mutationFn: async (payload) => {
      await apiClient.post(`/admin/users/${userId}/beta`, payload);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
