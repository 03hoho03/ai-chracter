import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import {
  toStoryImageArchiveView,
  type StoryImageArchiveItem,
  type StoryImageArchiveView,
} from "./toStoryImageArchiveView";
import { storyImageArchiveKeys } from "./keys";

// "더보기 > 이미지 보관함"을 연 동안에만 조회한다. gcTime: 0 — 응답의 그림 주소가 만료되는 서명 주소이고, 모달을 다시
// 열 때 직전 응답(방금 해금한 칸이 아직 잠긴 모습)을 먼저 그리지 않으려는 것이다(캐릭터 보관함과 같은 이유).
export function useStoryImageArchiveQuery(storyId: string, enabled: boolean) {
  return useQuery<StoryImageArchiveItem[], ApiError, StoryImageArchiveView>({
    queryKey: storyImageArchiveKeys.list(storyId),
    queryFn: async () =>
      (await apiClient.get<StoryImageArchiveItem[]>(`/stories/${storyId}/image-archive`)).data,
    select: toStoryImageArchiveView,
    enabled,
    gcTime: 0,
  });
}
