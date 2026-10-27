import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { contentKeys } from "./keys";
import type { ContentDetailResponse } from "./useContentDetailQuery";

/**
 * 원작 상세에 이 작품으로 만든 공개 소설을 보일지 바꾸는 `PUT /contents/{id}/derived-novels-visibility`(204). 표시만 바꾸고 허락·소설은
 * 그대로다. 작품 헤더 값이라 발행을 기다리지 않고 바로 적용된다.
 *
 * 스위치가 누르는 즉시 바뀌어 보이도록 상세 캐시를 먼저 고치고, 실패하면 되돌린다. 끝나면 상세를 다시 받아 서버 값으로 맞춘다 — 같은
 * 캐시를 원작 상세 화면도 읽는다.
 */
export function useUpdateDerivedNovelsVisibilityMutation(contentId: string) {
  const queryClient = useQueryClient();
  const detailKey = contentKeys.detail(contentId);
  return useMutation<void, ApiError, boolean, { previous: ContentDetailResponse | undefined }>({
    mutationFn: async (visible) => {
      await apiClient.put(`/contents/${contentId}/derived-novels-visibility`, { visible });
    },
    onMutate: async (visible) => {
      await queryClient.cancelQueries({ queryKey: detailKey });
      const previous = queryClient.getQueryData<ContentDetailResponse>(detailKey);
      if (previous) queryClient.setQueryData<ContentDetailResponse>(detailKey, { ...previous, derivedNovelsVisible: visible });
      return { previous };
    },
    onError: (_error, _visible, context) => {
      if (context?.previous) queryClient.setQueryData(detailKey, context.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: detailKey }),
  });
}
