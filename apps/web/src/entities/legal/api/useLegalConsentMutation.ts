import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import type { LegalConsentUnit } from "../model/consentUnits";

type LegalConsentPayload = { consents: LegalConsentUnit[] };

/** `POST /legal/consent` — 다시 동의한 단위들을 한 번에 보낸다. 서버가 단위마다 그 문서의 현행판 버전을 기록하므로 버전은
 * 보내지 않는다. 약관과 처리방침을 따로 보내면 한쪽만 기록되고 다른 쪽이 실패하는 중간 상태가 생긴다. */
export function useLegalConsentMutation() {
  return useMutation<void, ApiError, LegalConsentPayload>({
    mutationFn: async (payload) => {
      await apiClient.post("/legal/consent", payload);
    },
  });
}
