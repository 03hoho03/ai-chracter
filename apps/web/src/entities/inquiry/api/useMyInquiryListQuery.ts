import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { inquiryKeys } from "./keys";

export type MyInquiryListItem = components["schemas"]["MyInquiryListItem"];
export type MyInquiryListResponse = components["schemas"]["MyInquiryListResponse"];

/** `GET /me/inquiries` — 내 문의 목록. 항목이 적어 페이징하지 않는다(techspec.md §5-3, D-13과 같은
 * 이유). 4xx는 재시도해도 절대 성공하지 않으므로 즉시 에러 상태로 넘긴다(entities/legal의 동일 패턴). */
export function useMyInquiryListQuery() {
  return useQuery<MyInquiryListResponse, ApiError>({
    queryKey: inquiryKeys.list(),
    queryFn: async () => (await apiClient.get<MyInquiryListResponse>("/me/inquiries")).data,
    retry: (failureCount, error) => (error.status === 0 || error.status >= 500) && failureCount < 3,
  });
}
