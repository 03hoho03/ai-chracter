import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { inquiryKeys } from "./keys";

export type AdminInquiryDetailResponse = components["schemas"]["AdminInquiryDetailResponse"];

export function useInquiryDetailQuery(inquiryId: string) {
  return useQuery<AdminInquiryDetailResponse, ApiError>({
    queryKey: inquiryKeys.detail(inquiryId),
    queryFn: async () => (await apiClient.get<AdminInquiryDetailResponse>(`/admin/inquiries/${inquiryId}`)).data,
  });
}
