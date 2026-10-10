import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { creatorPayoutKeys, type CreatorPayoutStatus } from "./keys";

export type AdminCreatorPayoutListResponse = components["schemas"]["AdminCreatorPayoutListResponse"];
export type AdminCreatorPayoutItem = components["schemas"]["AdminCreatorPayoutItem"];
export type AdminCreatorPayoutDetail = components["schemas"]["AdminCreatorPayoutDetail"];
export type AdminCreatorPayoutWithholding = components["schemas"]["AdminCreatorPayoutWithholding"];
export type AdminUserCreatorPayoutResponse = components["schemas"]["AdminUserCreatorPayoutResponse"];

/** 한 상태의 지급, 오래된 신청부터(offset 페이지). 서버는 상태를 하나만 받는다 — "전체"가 없다. 탈퇴한 회원의 건도 나오고
 * 그 행은 닉네임이 `null` 이다. */
export function useCreatorPayoutListQuery(params: { page: number; status: CreatorPayoutStatus }) {
  return useQuery<AdminCreatorPayoutListResponse, ApiError>({
    queryKey: creatorPayoutKeys.list(params),
    queryFn: async () =>
      (
        await apiClient.get<AdminCreatorPayoutListResponse>("/admin/creator-payout/payouts", {
          params: { page: params.page, status: params.status },
        })
      ).data,
  });
}

/** 지급 건 하나. 수취인은 마스킹 값뿐이다 — 원문은 사유를 적고 따로 연다(`features/view-payee-info`). 수취인 실명을
 * 복호화하지 못해도(암호화 키 분실) 조회는 거부되지 않고 `payeeInfoReadable` 거짓·`maskedName` null 로 온다 — 그 건도
 * 열어서 반려·보류할 수 있어야 한다. */
export function useCreatorPayoutDetailQuery(payoutId: string) {
  return useQuery<AdminCreatorPayoutDetail, ApiError>({
    queryKey: creatorPayoutKeys.detail(payoutId),
    queryFn: async () =>
      (
        await apiClient.get<AdminCreatorPayoutDetail>(
          `/admin/creator-payout/payouts/${encodeURIComponent(payoutId)}`,
        )
      ).data,
  });
}

/** 회원 상세의 정산 섹션: 신청 이력 전부, 적립 잔액(음수일 수 있다), 최근 확정 12개, 최근 지급 20개. 탈퇴 회원은 404 다
 * (회원 상세 자체가 404 라 이 섹션이 열릴 일이 없다). */
export function useUserCreatorPayoutQuery(userId: string) {
  return useQuery<AdminUserCreatorPayoutResponse, ApiError>({
    queryKey: creatorPayoutKeys.user(userId),
    queryFn: async () =>
      (
        await apiClient.get<AdminUserCreatorPayoutResponse>(
          `/admin/users/${encodeURIComponent(userId)}/creator-payout`,
        )
      ).data,
  });
}
