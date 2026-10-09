import type { components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { creatorPayoutKeys } from "@/entities/creator-payout";
import { apiClient } from "@/shared/api/client";

type ApplyCreatorPayoutResponse = components["schemas"]["ApplyCreatorPayoutResponse"];

/** 정산을 신청한다. 보내는 것은 수집·이용 동의 하나다(서버가 동의 시각과 그때의 처리방침 버전을 남긴다).
 *
 * 성공이든 실패든 신청 상태를 다시 읽는다 — 성공은 대기 중으로 바뀌고, 거절도 대부분 화면이 본 자격이 낡았다는
 * 뜻이다(그 사이 다른 창에서 신청했거나, 작품을 내렸거나, 인증 상태가 바뀌었다). */
export function useApplyCreatorPayoutMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiClient
        .post<ApplyCreatorPayoutResponse>("/me/creator-payout/application", { agreed: true })
        .then((res) => res.data),
    onSettled: () => queryClient.invalidateQueries({ queryKey: creatorPayoutKeys.summary() }),
  });
}
