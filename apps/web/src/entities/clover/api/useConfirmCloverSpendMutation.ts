import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { cloverKeys } from "./keys";

/** 소진 시 **하루 1회** 확인. 확인 사실은 서버가 KST 날짜로 들고
 * 있고(`users.clover_spend_confirmed_on`) 자정에 리셋된다 — 기기를 바꿔도 유지되고, 브라우저
 * 저장소를 쓰지 않는 이유가 그것이다.
 *
 * 204라 반환값이 없다. 성공하면 `spendConfirmedToday`가 바뀌므로 잔액 쿼리를 invalidate 한다. */
export function useConfirmCloverSpendMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => apiClient.post<void>("/me/clover/spend-confirmation").then(() => undefined),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
    },
  });
}
