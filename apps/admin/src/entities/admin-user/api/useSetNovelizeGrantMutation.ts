import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminUserNovelizeGrantRequest = components["schemas"]["AdminUserNovelizeGrantRequest"];

/** POST /admin/users/{id}/novelize-grant — 응답 204(본문 없음). 베타 토글과 같은 모양으로 허용·회수를
 * `granted` 한 필드로 받고, 공백 `adminComment`는 BE가 422로 거부한다(호출부 스키마가 먼저 막는다).
 * 허용은 서버 env 명단 안의 계정에만 되고, 명단 밖이면 BE가 422 `detail.code === "NOVELIZE_GRANT_NOT_ALLOWLISTED"`로
 * 거부한다 — 그 code는 OpenAPI에 나오지 않아 호출부가 문자열로 가른다. 회수는 명단과 상관없이 늘 된다.
 * 상세 응답의 허용 시각(`novelizeGrantedAt`)이 바뀌므로 유저 쿼리 전체를 끊는다. */
export function useSetNovelizeGrantMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, AdminUserNovelizeGrantRequest>({
    mutationFn: async (payload) => {
      await apiClient.post(`/admin/users/${userId}/novelize-grant`, payload);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
