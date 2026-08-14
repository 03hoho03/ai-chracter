import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { generatedImagesKeys } from "./keys";

export type GeneratedImageItem = components["schemas"]["GeneratedImageItem"];

// prd-image-library US-004 — 빌더 피커(features/select-generated-image)와 보관함
// (pages/studio-images)이 공유하는 생성 이미지 목록. features끼리 직접 import가 금지라
// entities로 내렸다(apps/web/CLAUDE.md FSD 의존 방향).
//
// refetchOnWindowFocus: true — 새 탭에서 이미지 생성을 마치고 빌더 탭으로 돌아왔을 때(포커스
// 복귀) 자동으로 최신 목록을 반영해야 해서 명시적으로 켠다(techspec-builder-story.md §2).
// gcTime: 0 — 응답 항목의 imageUrl이 presigned GET URL이라 캐시 대상이 아니다
// (apps/web/CLAUDE.md 자산 규칙, useCharacterImageArchiveQuery와 동일).
export function useGeneratedImagesQuery(enabled: boolean) {
  return useQuery<GeneratedImageItem[], ApiError>({
    queryKey: generatedImagesKeys.list(),
    queryFn: async () => (await apiClient.get<GeneratedImageItem[]>("/me/generated-images")).data,
    enabled,
    refetchOnWindowFocus: true,
    gcTime: 0,
  });
}
