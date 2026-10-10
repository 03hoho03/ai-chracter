import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { creatorPayoutKeys } from "./keys";

export type AdminCreatorPayoutTransferRequest = components["schemas"]["AdminCreatorPayoutTransferRequest"];
export type AdminCreatorPayoutPayeeReplaceRequest = components["schemas"]["AdminCreatorPayoutPayeeReplaceRequest"];

const payoutPath = (payoutId: string, action: "transfer" | "return" | "hold" | "payee-info") =>
  `/admin/creator-payout/payouts/${encodeURIComponent(payoutId)}/${action}`;

/**
 * 성공이 아니라 끝날 때마다 다시 읽는다 — 409(이미 처리됨·수취인 탈퇴 여부가 바뀜)·404 는 화면의 값이 낡았다는 뜻이라
 * 실패에서도 새 상태를 보여야 한다. 큐·상세·회원 섹션이 모두 `all` 하위다.
 */
function useInvalidatePayouts() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: creatorPayoutKeys.all });
}

/** 은행에서 마친 이체를 기록한다. 처리 중·보류 건만. 이체일은 신청일(KST)부터 오늘(KST)까지. */
export function useTransferCreatorPayoutMutation(payoutId: string) {
  const invalidate = useInvalidatePayouts();
  return useMutation<void, ApiError, AdminCreatorPayoutTransferRequest>({
    mutationFn: async (body) => {
      await apiClient.post(payoutPath(payoutId, "transfer"), body);
    },
    onSettled: invalidate,
  });
}

/** 반려. 사유는 신청자 정산 화면에 그대로 보이고, 금액은 잔액으로 돌아간다. 탈퇴한 회원의 건은 서버가 거부한다. */
export function useReturnCreatorPayoutMutation(payoutId: string) {
  const invalidate = useInvalidatePayouts();
  return useMutation<void, ApiError, { reasonText: string }>({
    mutationFn: async (body) => {
      await apiClient.post(payoutPath(payoutId, "return"), body);
    },
    onSettled: invalidate,
  });
}

/** 보류. 탈퇴한 회원의 처리 중인 건만. 사유는 운영자만 본다. */
export function useHoldCreatorPayoutMutation(payoutId: string) {
  const invalidate = useInvalidatePayouts();
  return useMutation<void, ApiError, { reasonText: string }>({
    mutationFn: async (body) => {
      await apiClient.post(payoutPath(payoutId, "hold"), body);
    },
    onSettled: invalidate,
  });
}

/** 수취 정보 교체. 탈퇴한 회원의 처리 중·보류 건만. 값은 이 요청 본문에만 실리고 감사 로그에는 사유만 남는다. */
export function useReplaceCreatorPayoutPayeeMutation(payoutId: string) {
  const invalidate = useInvalidatePayouts();
  return useMutation<void, ApiError, AdminCreatorPayoutPayeeReplaceRequest>({
    mutationFn: async (body) => {
      await apiClient.put(payoutPath(payoutId, "payee-info"), body);
    },
    onSettled: invalidate,
    // 요청 본문(주민등록번호·계좌번호)은 뮤테이션의 `variables` 로 남는다. 쓰는 화면이 사라지면 기본 5분을 기다리지 않고
    // 바로 버린다(화면에 있는 동안은 성공 뒤 호출부가 `reset` 으로 지운다).
    gcTime: 0,
  });
}
