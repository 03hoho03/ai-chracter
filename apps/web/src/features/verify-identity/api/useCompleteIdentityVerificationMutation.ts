import type { components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cloverKeys } from "@/entities/clover";
import { sessionKeys } from "@/entities/session";
import { apiClient } from "@/shared/api/client";

export type CompleteIdentityVerificationResponse = components["schemas"]["CompleteIdentityVerificationResponse"];

/** 서버가 포트원에 인증 결과를 다시 물어 저장한다.
 *
 * 끝날 때마다 세션을 다시 읽는다 — 성공이면 인증 여부가 바뀌었고, "이미 인증한 계정"(다른 탭에서 마쳤다) 거절도 이
 * 탭의 세션이 낡았다는 뜻이다. 성공하면 출석 가능 여부(잔액 응답)와 미션 상태도 게이트가 풀려 바뀐다. */
export function useCompleteIdentityVerificationMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (identityVerificationId: string) =>
      apiClient
        .post<CompleteIdentityVerificationResponse>(
          `/me/identity-verifications/${encodeURIComponent(identityVerificationId)}/complete`,
        )
        .then((res) => res.data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
      void queryClient.invalidateQueries({ queryKey: cloverKeys.missions() });
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
    },
  });
}
