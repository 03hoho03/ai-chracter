import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminImageGenerationKeys, type AdminImageGenerationListParams } from "./keys";

export type AdminImageGenerationListResponse = components["schemas"]["AdminImageGenerationListResponse"];

/** offset 페이지네이션(20건), 프롬프트·이미지는
 * 응답에 없다(사유 게이트 뒤 유저 단위 열람 화면 몫). */
export function useImageGenerationListQuery(params: AdminImageGenerationListParams) {
  return useQuery<AdminImageGenerationListResponse, ApiError>({
    queryKey: adminImageGenerationKeys.list(params),
    queryFn: async () =>
      (
        await apiClient.get<AdminImageGenerationListResponse>("/admin/image-generations", {
          params: {
            page: params.page,
            q: params.q,
            status: params.status,
            style: params.style,
            from: params.from,
            to: params.to,
          },
        })
      ).data,
  });
}
