import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { imageModelKeys } from "./keys";

export type ImageModel = components["schemas"]["ImageModelItem"];

// 생성에 쓸 수 있는 모델 + 각 모델 지원 종횡비. capability 메타라 세션 중 바뀌지 않으므로
// staleTime을 무한으로 둔다(모델 선택 시 미지원 비율을 비활성화하는 데 쓰인다).
export function useImageModelsQuery() {
  return useQuery<ImageModel[], ApiError>({
    queryKey: imageModelKeys.all,
    queryFn: async () => (await apiClient.get<ImageModel[]>("/images/models")).data,
    staleTime: Number.POSITIVE_INFINITY,
  });
}
