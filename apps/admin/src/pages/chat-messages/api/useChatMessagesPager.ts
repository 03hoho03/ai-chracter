import type { ApiError } from "@ai-character-chat/api-types";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiClient } from "@/shared/lib/api/client";

import { chatMessagesKeys, type ChatMessagesCursor } from "./keys";
import type { AdminChatMessagesResponse } from "./useViewChatMutation";

/** 더보기(`GET .../messages`)는 로그를 쌓지 않는 순수 조회라 쿼리 캐시를 태우지만,
 * `useInfiniteQuery`는 쓰지 않는다 — 첫 페이지는 이 훅이 아니라 별도의 POST 뮤테이션
 * (`useViewChatMutation`)에서 오고, 그 결과를 이 쿼리 캐시에 억지로 끼워 맞추면(`setQueryData`로
 * 0번째 페이지를 시뮬레이션하는 등) "이 호출만 로그를 쌓는다"는 두 엔드포인트의 실제 차이가
 * 코드에서 안 보이게 된다. 그래서 "더 보기" 클릭마다 `fetchPage`로 `queryClient.fetchQuery`를
 * 명령형으로 호출한다 — 여전히 진짜 쿼리 캐시/키/재시도 정책(GET이므로 기본 `retry: 3`)을 그대로
 * 쓰지만, 컴포넌트가 반응형으로 구독하지 않으므로 cursor state 변경과 실제 fetch 사이에 불필요한
 * 재렌더나 경쟁상태가 끼어들 여지가 없다 — 페이지 누적(`ChatMessagesPage`의 로컬 state)은
 * 호출부가 await 후 정확히 한 번만 수행한다. `UseQueryResult`를 돌려주지 않으므로 이름도
 * `use*Query`가 아니라 pager다. */
export function useChatMessagesPager(roomId: string) {
  const queryClient = useQueryClient();
  const [isFetching, setIsFetching] = useState(false);

  const fetchPage = async (cursor: ChatMessagesCursor) => {
    setIsFetching(true);
    try {
      return await queryClient.fetchQuery<AdminChatMessagesResponse, ApiError>({
        queryKey: chatMessagesKeys.list(roomId, cursor),
        queryFn: async () =>
          (
            await apiClient.get<AdminChatMessagesResponse>(`/admin/chat-rooms/${roomId}/messages`, {
              params: { beforeCreatedAt: cursor.beforeCreatedAt, beforeId: cursor.beforeId },
            })
          ).data,
      });
    } finally {
      setIsFetching(false);
    }
  };

  return { isFetching, fetchPage };
}
