import type { components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSetAtom } from "jotai";

import { commentDraftLogoutRevisionAtom, commentKeys } from "@/entities/comment";
import { notificationKeys } from "@/entities/notification";
import { personaKeys } from "@/entities/persona";
import { sessionKeys } from "@/entities/session";
import { apiClient } from "@/shared/api/client";

type WithdrawRequest = components["schemas"]["WithdrawRequest"];

/** apps/web/CLAUDE.md — 세션 소실을 이미 마운트된 컴포넌트에 즉시 반영해야 하므로 features/logout과 동일하게 resetQueries를 쓴다.
 *
 * 바디는 비밀번호 계정만 보낸다. 소셜 계정은 서버가 비밀번호를 묻지 않으므로 예전처럼 바디 없이 보낸다. */
export function useWithdrawAccountMutation() {
  const queryClient = useQueryClient();
  const setLogoutRevision = useSetAtom(commentDraftLogoutRevisionAtom);

  return useMutation({
    mutationFn: (payload?: WithdrawRequest) =>
      apiClient.delete<void>("/me", payload ? { data: payload } : undefined).then((res) => res.data),
    // 같은 정리를 `features/logout`도 한다 — features끼리는 서로 import할 수 없어 두 벌이다. 로그인 사용자별
    // 캐시를 새로 만들면 양쪽 onSuccess에 함께 더한다.
    onSuccess: () => {
      setLogoutRevision((revision) => revision + 1);
      void queryClient.resetQueries({ queryKey: commentKeys.all });
      void queryClient.resetQueries({ queryKey: notificationKeys.all });
      void queryClient.resetQueries({ queryKey: personaKeys.all });
      void queryClient.resetQueries({ queryKey: sessionKeys.current() });
    },
  });
}
