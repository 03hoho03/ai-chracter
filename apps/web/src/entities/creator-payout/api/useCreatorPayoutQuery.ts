import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient, isApiError } from "@/shared/api/client";

import { isCreatorPayoutUnavailableError } from "../model/creatorPayoutError";
import { formatPayoutRate } from "../model/payoutRate";
import { creatorPayoutKeys } from "./keys";

export type CreatorPayoutResponse = components["schemas"]["CreatorPayoutResponse"];
export type CreatorPayoutApplication = components["schemas"]["CreatorPayoutApplicationView"];
export type CreatorPayoutEligibility = components["schemas"]["CreatorPayoutEligibilityView"];

/** 정산 신청 상태·신청 자격·적립 잔액·적립 비율. 재시도 규칙은 전역 기본값(네트워크·5xx 만 3회)을 따르되, 스위치가
 * 꺼진 503 은 기다려도 풀리지 않아 재시도하지 않는다 — 재시도하면 "이용할 수 없어요"가 백오프 동안 몇 초 늦게 뜬다.
 *
 * `enabled` 는 정산이 열린 계정에서만 묻게 하는 자리(정산 화면 밖의 적립 안내)가 쓴다. */
export function useCreatorPayoutQuery({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery<CreatorPayoutResponse, ApiError>({
    queryKey: creatorPayoutKeys.summary(),
    queryFn: async () => (await apiClient.get<CreatorPayoutResponse>("/me/creator-payout")).data,
    enabled,
    retry: (failureCount, error) =>
      !isCreatorPayoutUnavailableError(error) &&
      isApiError(error) &&
      (error.status === 0 || error.status >= 500) &&
      failureCount < 3,
  });
}

/** 정산 밖에서 적립 비율을 말할 자리(소설 만들기 허락 설명)의 비율 표기. 정산이 닫혀 있거나(`isEnabled` 거짓) 값이
 * 아직 없거나 조회가 실패하면 `null` 이다 — 그때는 안내를 숨긴다. 비율은 서버 설정이라 웹이 숫자를 지어내지 않는다. */
export function useCreatorPayoutRate(isEnabled: boolean): string | null {
  const query = useCreatorPayoutQuery({ enabled: isEnabled });
  return isEnabled && query.data ? formatPayoutRate(query.data.rateBps) : null;
}
