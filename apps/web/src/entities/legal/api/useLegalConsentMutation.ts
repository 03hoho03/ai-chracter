import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

type LegalConsentRequest = components["schemas"]["LegalConsentRequest"];

/** `POST /legal/consent` — 서버가 최신 게시본 버전을 다시 조회해 기록하므로 요청의 `version`은
 * 신뢰되지 않지만, 스키마상 필수 필드라 호출부가 방금 보여준 문서의 version을 그대로 보낸다. */
export function useLegalConsentMutation() {
  return useMutation<void, ApiError, LegalConsentRequest>({
    mutationFn: async (payload) => {
      await apiClient.post("/legal/consent", payload);
    },
  });
}
