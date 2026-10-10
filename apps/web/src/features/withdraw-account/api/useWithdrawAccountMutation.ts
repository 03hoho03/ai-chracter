import type { components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSetAtom } from "jotai";

import { chatRoomKeys } from "@/entities/chat-room";
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
      // 내 방 목록 키는 보는 사람 id 별이라, id 앞에서 끊긴 접두로 어느 계정의 것이든 모두 비운다. 리셋이 아니라
      // 지우기다 — 리셋은 화면에 붙은 목록을 곧바로 다시 받아 이미 지워진 쿠키로 401 이 난다. 키에 id 가 있어
      // 아래 세션 리셋으로 다음 렌더에서 목록 훅이 빈 id 키(조회 꺼짐)로 옮겨 가므로, 옛 데이터는 지우기만 하면 된다.
      queryClient.removeQueries({ queryKey: chatRoomKeys.myLists() });
      void queryClient.resetQueries({ queryKey: sessionKeys.current() });
    },
  });
}
