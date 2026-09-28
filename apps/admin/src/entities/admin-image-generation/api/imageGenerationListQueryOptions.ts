import type { ApiError, components } from "@ai-character-chat/api-types";
import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminImageGenerationKeys, type AdminImageGenerationListParams } from "./keys";

export type AdminImageGenerationListResponse = components["schemas"]["AdminImageGenerationListResponse"];

/** 목록 표와 스타일 필터가 같은 응답을 읽는다(필터 선택지의 이름이 목록 응답에 실려 온다) — 키와
 * 요청을 한 곳에 두어 두 구독이 같은 캐시 항목을 공유하고 요청도 한 번만 나가게 한다. */
export const imageGenerationListQueryOptions = (params: AdminImageGenerationListParams) =>
  queryOptions<AdminImageGenerationListResponse, ApiError>({
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
