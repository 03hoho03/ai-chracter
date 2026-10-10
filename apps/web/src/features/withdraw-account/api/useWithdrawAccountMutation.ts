import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { useClearViewerSession } from "@/entities/session";
import { apiClient } from "@/shared/api/client";

type WithdrawRequest = components["schemas"]["WithdrawRequest"];

/** 로그아웃과 같은 정리(`useClearViewerSession`)를 한다.
 *
 * 바디는 비밀번호 계정만 보낸다. 소셜 계정은 서버가 비밀번호를 묻지 않으므로 예전처럼 바디 없이 보낸다. */
export function useWithdrawAccountMutation() {
  const clearViewerSession = useClearViewerSession();

  return useMutation({
    mutationFn: (payload?: WithdrawRequest) =>
      apiClient.delete<void>("/me", payload ? { data: payload } : undefined).then((res) => res.data),
    onSuccess: () => clearViewerSession(),
  });
}
