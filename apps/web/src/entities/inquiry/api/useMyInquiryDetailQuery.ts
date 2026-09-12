import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { inquiryKeys } from "./keys";

export type MyInquiryDetailResponse = components["schemas"]["MyInquiryDetailResponse"];

/** `GET /me/inquiries/{id}` — 내 문의 상세. 남의 문의는 404다(403이 아니라 — 존재 여부를 흘리지
 * 않는다, techspec.md §4-4). 4xx는 재시도해도 절대 성공하지 않으므로 즉시 에러 상태로 넘긴다
 * (entities/legal의 동일 패턴). */
export function useMyInquiryDetailQuery(id: string) {
  return useQuery<MyInquiryDetailResponse, ApiError>({
    queryKey: inquiryKeys.detail(id),
    queryFn: async () => (await apiClient.get<MyInquiryDetailResponse>(`/me/inquiries/${id}`)).data,
    retry: (failureCount, error) => (error.status === 0 || error.status >= 500) && failureCount < 3,
  });
}
