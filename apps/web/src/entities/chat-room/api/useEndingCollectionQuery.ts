import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { chatRoomKeys } from "./keys";

export type EndingCollectionItem = components["schemas"]["EndingCollectionItem"];

// "더보기 > 엔딩 컬렉션" 클릭 시점에만 온디맨드 조회한다
// (useChatRoomPlayGuideQuery와 동일한 enabled 패턴).
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
    // 에필로그 속 그림 주소가 만료되는 서명 주소라, 모달을 다시 열 때 직전 응답을 먼저 그리지 않는다.
    gcTime: 0,
  });
}
