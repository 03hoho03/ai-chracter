import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import type { NovelPermission } from "../model/novelPermission";

/** 발행 뒤 소설 만들기 허락을 바꾸는 `PUT /contents/{id}/novel-permission`. 204 라 돌려줄 값이 없고, 캐시 무효화는
 * 호출부가 맡는다(공개 범위 전환과 같은 모양). */
export function useUpdateNovelPermissionMutation(contentId: string) {
  return useMutation<void, ApiError, NovelPermission>({
    mutationFn: async (novelPermission) => {
      await apiClient.put(`/contents/${contentId}/novel-permission`, { novelPermission });
    },
  });
}
