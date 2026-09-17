import type { ApiError } from "@ai-character-chat/api-types";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiClient } from "@/shared/lib/api/client";

import { imageGenerationDetailKeys } from "./keys";
import type { AdminImageGenerationDetailListResponse } from "./useViewImageGenerationsMutation";

/** 더보기(`GET .../image-generations`)는 로그를 쌓지 않는 순수 조회라 쿼리 캐시를 태우지만,
 * `useInfiniteQuery`는 쓰지 않는다 — `useChatMessagesPager`와 같은 이유다: 첫 페이지는 이 훅이
 * 아니라 별도의 POST 뮤테이션(`useViewImageGenerationsMutation`)에서 오고, 그 결과를 이 쿼리
 * 캐시에 억지로 끼워 맞추면 "이 호출만 로그를 쌓는다"는 두 엔드포인트의 실제 차이가 코드에서
 * 안 보이게 된다. `fetchPage`로 `queryClient.fetchQuery`를 명령형으로 호출해 진짜 쿼리 캐시/키/
 * 재시도 정책(GET이므로 기본 `retry: 3`)은 그대로 쓰되, 컴포넌트가 반응형으로 구독하지 않는다.
 * 채팅과 달리 커서가 아니라 페이지 번호라 `page`를 그대로 인자로 받는다. */
export function useImageGenerationsPager(userId: string) {
  const queryClient = useQueryClient();
  const [isFetching, setIsFetching] = useState(false);

  const fetchPage = async (page: number) => {
    setIsFetching(true);
    try {
      return await queryClient.fetchQuery<AdminImageGenerationDetailListResponse, ApiError>({
        queryKey: imageGenerationDetailKeys.list(userId, page),
        queryFn: async () =>
          (
            await apiClient.get<AdminImageGenerationDetailListResponse>(
              `/admin/users/${userId}/image-generations`,
              { params: { page } },
            )
          ).data,
      });
    } finally {
      setIsFetching(false);
    }
  };

  return { isFetching, fetchPage };
}
