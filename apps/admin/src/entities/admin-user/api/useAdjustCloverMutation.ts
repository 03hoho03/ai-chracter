import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminUserCloverRequest = components["schemas"]["AdminUserCloverRequest"];

/** POST /admin/users/{id}/clover — 응답 204(본문 없음). clover-techspec.md §4-2:
 * 지급과 회수를 **부호 있는 `amount` 한 필드**로 받는다(`AdminUserRateLimitExemptRequest`가
 * 켜기/끄기를 `exempt` 한 필드로 받는 것과 같은 관례). 호출부는 지급·회수를 별개 조치로
 * 나눠 보여주고 여기서 부호만 붙인다 — 운영자가 `-`를 손으로 치지 않게 하려는 것이다.
 *
 * 🔴 `idempotencyKey`는 **호출부가 요청마다 새로 만든다**(clover-goal-prompt.md CL-8).
 * 출석처럼 서버가 `(user, 날짜)`로 파생할 수 없다 — 같은 어드민이 같은 유저에게 같은 금액을
 * **의도적으로 두 번** 줄 수 있어야 하기 때문이다. 막으려는 것은 "두 번 주는 것"이 아니라
 * **한 번 누른 것이 두 번 도착하는 것**(더블클릭·네트워크 재시도)이고, 그때 BE가 409를 낸다.
 *
 * 잔액(상세)과 원장이 둘 다 바뀌므로 `adminUserKeys.all`을 통째로 끊는다. 작품 상태는
 * 건드리지 않아 작품 쿼리는 끊을 게 없다(useSetRateLimitExemptMutation과 같다).
 *
 * 🔴 `onSuccess`가 아니라 `onSettled`인 이유: **409에서도 잔액이 이미 움직여 있다.** 같은 키가
 * 두 번 도착했다는 뜻이므로 첫 요청이 원장을 남겼고, 호출부는 그때 "잔액은 한 번만 반영됐어요"를
 * 말한다 — `onSuccess`로 두면 그 말과 달리 화면이 옛 잔액을 계속 보여준다. 422·네트워크 실패에서
 * 도는 재조회는 무해하다(잔액이 그대로라는 것을 확인할 뿐이다). */
export function useAdjustCloverMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, AdminUserCloverRequest>({
    mutationFn: async (payload) => {
      await apiClient.post(`/admin/users/${userId}/clover`, payload);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
