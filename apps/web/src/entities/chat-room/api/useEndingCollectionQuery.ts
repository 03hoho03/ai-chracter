import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { chatRoomKeys } from "./keys";

export type EndingCollectionItem = components["schemas"]["EndingCollectionItem"];

// techspec-chat-story.md §6, US-069/070 — "더보기 > 엔딩 컬렉션" 클릭 시점에만 온디맨드 조회한다
// (US-067 useChatRoomPlayGuideQuery와 동일한 enabled 패턴).
export function useEndingCollectionQuery(startingSetupId: string, enabled: boolean) {
  return useQuery<EndingCollectionItem[], ApiError>({
    queryKey: chatRoomKeys.endingCollection(startingSetupId),
    queryFn: async () =>
      (
        await apiClient.get<EndingCollectionItem[]>(
          `/stories/starting-setups/${startingSetupId}/ending-collection`,
        )
      ).data,
    enabled,
  });
}
