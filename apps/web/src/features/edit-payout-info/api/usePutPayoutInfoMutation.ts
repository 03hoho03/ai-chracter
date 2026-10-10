import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { creatorPayoutKeys } from "@/entities/creator-payout";
import { apiClient } from "@/shared/api/client";

import type { PutPayoutInfoRequest } from "../model/formToServer";

/** 지급 정보를 등록하거나 새로 입력한다(204, 본문 없음). 성공이든 실패든 정산 요약을 다시 읽는다 — 성공은 마스킹한
 * 표시값이 바뀌고, 거절(처리 중 지급·자격)도 대부분 화면이 본 상태가 낡았다는 뜻이다.
 *
 * 다시 읽기를 기다린 뒤에 끝난다 — 응답에 새 표시값이 없어서, 기다리지 않으면 저장 직후 화면이 "등록한 정보 없음"
 * 그대로라 폼이 닫히지 못한다.
 *
 * `gcTime: 0` — 뮤테이션 캐시는 요청 본문(실명·주민등록번호·계좌번호 원문)을 끝난 뒤에도 기본 5분 쥐고 있다. 폼이
 * 사라지면 바로 버린다(실패하면 폼이 값을 쥐고 있어 다시 보낼 수 있다). */
export function putPayoutInfoMutationOptions(queryClient: QueryClient) {
  return {
    mutationFn: (body: PutPayoutInfoRequest) => apiClient.put("/me/creator-payout/payout-info", body),
    onSettled: () => queryClient.invalidateQueries({ queryKey: creatorPayoutKeys.summary() }),
    gcTime: 0,
  };
}

export function usePutPayoutInfoMutation() {
  const queryClient = useQueryClient();
  return useMutation(putPayoutInfoMutationOptions(queryClient));
}
