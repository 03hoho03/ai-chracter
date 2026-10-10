import type { components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { creatorPayoutKeys } from "./keys";

export type RequestCreatorPayoutResponse = components["schemas"]["RequestPayoutResponse"];

/** 확정 잔액 전액의 지급을 신청한다(금액은 보내지 않는다 — 서버가 신청 순간의 잔액을 쓴다). `forWithdrawal` 은 탈퇴
 * 확인에서만 참이다: 잔액이 최소 지급액보다 적어도 신청을 받는다.
 *
 * 정산 화면과 탈퇴 확인이 함께 쓰므로 엔티티에 둔다. 성공이든 실패든 정산 요약과 지급 내역을 다시 읽는다 — 성공은 잔액과
 * 처리 중 지급이 바뀌고, 거절도 대부분 화면이 본 잔액·지급 정보가 낡았다는 뜻이다. */
export function useRequestCreatorPayoutMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ forWithdrawal }: { forWithdrawal: boolean }) =>
      apiClient
        .post<RequestCreatorPayoutResponse>("/me/creator-payout/payouts", { forWithdrawal })
        .then((res) => res.data),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: creatorPayoutKeys.summary() }),
        queryClient.invalidateQueries({ queryKey: creatorPayoutKeys.payouts() }),
      ]),
  });
}
