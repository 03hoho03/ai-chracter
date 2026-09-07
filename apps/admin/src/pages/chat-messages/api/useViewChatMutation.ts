import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminUserKeys } from "@/entities/admin-user";
import { apiClient } from "@/shared/lib/api/client";

export type AdminChatRoomViewRequest = components["schemas"]["AdminChatRoomViewRequest"];
export type AdminChatMessagesResponse = components["schemas"]["AdminChatMessagesResponse"];
export type AdminChatMessageItem = components["schemas"]["AdminChatMessageItem"];

/** 이 훅의 호출 1회 = 서버 감사 로그 1행(techspec §4-5, `apps/api/CLAUDE.md`). `useMutation`
 * 기본값이 이미 `retry: 0`이라(useQuery와 다른 점) 별도 설정 없이도 자동 재시도로 로그가
 * 중복 적재될 위험이 없다. 결과를 쿼리 캐시에 남기지 않는 이유도 같다 — 이 응답은 "그 순간의
 * 열람 결과"일 뿐 재사용할 서버 상태가 아니다. 페이지 누적(더보기와의 합산)은 호출부
 * (`ChatMessagesPage`)의 로컬 state가 맡는다.
 *
 * 성공 시 유저 쿼리를 무효화한다 — 이 POST가 만든 감사 로그 행이 유저 상세의 "조치 이력" 표에
 * "채팅 열람"으로 나오기 때문. UserActionConfirmModal이 작품 쿼리를 호출부에서 끊는 건 entity
 * 뮤테이션이 다른 entity 키를 import하면 크로스 import가 돼서인데(useSuspendUserMutation 주석),
 * 이 훅은 pages 세그먼트라 entities를 내려다보는 정상 방향 의존이다 — 다른 어드민 뮤테이션들처럼
 * 훅 안 `onSuccess`에서 끊는다. `adminUserKeys.all`이 정적 배열이라 userId를 몰라도 된다. */
export function useViewChatMutation(roomId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminChatMessagesResponse, ApiError, AdminChatRoomViewRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminChatMessagesResponse>(`/admin/chat-rooms/${roomId}/view`, payload)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
