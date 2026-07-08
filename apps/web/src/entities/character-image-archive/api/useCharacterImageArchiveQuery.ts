import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { characterImageArchiveKeys } from "./keys";

export type ImageArchiveItem = components["schemas"]["ImageArchiveItem"];

// techspec-chat-character.md §2, US-074/075 — "더보기 > 이미지 보관함" 클릭 시점에만 온디맨드
// 조회한다(US-067/069 useChatRoomPlayGuideQuery/useEndingCollectionQuery와 동일한 enabled 패턴).
export function useCharacterImageArchiveQuery(characterId: string, enabled: boolean) {
  return useQuery<ImageArchiveItem[], ApiError>({
    queryKey: characterImageArchiveKeys.list(characterId),
    queryFn: async () =>
      (await apiClient.get<ImageArchiveItem[]>(`/characters/${characterId}/image-archive`)).data,
    enabled,
  });
}
