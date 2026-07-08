import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { generatedImagesKeys } from "./keys";

export type GeneratedImageItem = components["schemas"]["GeneratedImageItem"];

// techspec-builder-story.md §2 — 새 탭에서 이미지 생성을 마치고 빌더 탭으로 돌아왔을 때(포커스 복귀)
// 자동으로 최신 목록을 반영해야 해서 refetchOnWindowFocus를 명시적으로 켠다(TanStack Query 기본값에
// 기대지 않음). 피커 모달이 열려있을 때만 온디맨드 조회한다(useCharacterImageArchiveQuery와 동일한
// enabled 패턴).
export function useGeneratedImagesQuery(enabled: boolean) {
  return useQuery<GeneratedImageItem[], ApiError>({
    queryKey: generatedImagesKeys.list(),
    queryFn: async () => (await apiClient.get<GeneratedImageItem[]>("/me/generated-images")).data,
    enabled,
    refetchOnWindowFocus: true,
  });
}
