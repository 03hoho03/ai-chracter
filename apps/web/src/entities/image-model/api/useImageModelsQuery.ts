import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { imageModelKeys } from "./keys";

export type ImageModel = components["schemas"]["ImageModelItem"];

// 생성에 쓸 수 있는 모델 + 각 모델 지원 종횡비·스타일·가용성. **가용성은 세션 중에 바뀐다** —
// 집 PC 추론 서버가 꺼지면 캐시된 "가능"이 바로 틀린 값이 된다.
// staleTime을 서버의 capabilities TTL(30초 — 실측)에 맞춰 유한하게 둔다.
// **권위는 서버다**: 실제 차단은 POST /images/generate의 사전 확인이 하고, 이 값은 화면에 보이는
// 목록이 얼마나 자주 새로고침되는지(UI 신선도)만 좌우한다.
export function useImageModelsQuery() {
  return useQuery<ImageModel[], ApiError>({
    queryKey: imageModelKeys.all,
    queryFn: async () => (await apiClient.get<ImageModel[]>("/images/models")).data,
    staleTime: 30_000,
  });
}
