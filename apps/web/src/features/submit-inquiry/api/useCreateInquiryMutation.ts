import type { components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { inquiryKeys } from "@/entities/inquiry";
import { apiClient } from "@/shared/lib/api/client";

type InquiryCreateRequest = components["schemas"]["InquiryCreateRequest"];
type InquiryCreateResponse = components["schemas"]["InquiryCreateResponse"];

/** `POST /inquiries` — 접수 성공 시 내 문의 목록/상세 캐시를 무효화한다(techspec.md §5-3). */
export function useCreateInquiryMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: InquiryCreateRequest) =>
      apiClient.post<InquiryCreateResponse>("/inquiries", payload).then((res) => res.data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: inquiryKeys.all });
    },
  });
}
