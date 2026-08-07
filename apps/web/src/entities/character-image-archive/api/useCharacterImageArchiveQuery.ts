import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { characterImageArchiveKeys } from "./keys";

export type ImageArchiveItem = components["schemas"]["ImageArchiveItem"];

// techspec-chat-character.md §2, US-074/075 — "더보기 > 이미지 보관함" 클릭 시점에만 온디맨드
// 조회한다(US-067/069 useChatRoomPlayGuideQuery/useEndingCollectionQuery와 동일한 enabled 패턴).
//
// gcTime: 0 — 모달을 닫으면 캐시를 버려, 다시 열 때 이전 스냅샷을 먼저 그리지 않는다. 기본
// gcTime(5분)이면 재오픈 순간 직전 조회 결과가 그대로 페인트된 뒤 리페치 응답이 와야 교체되는데,
// 그 사이 방금 해금한 이미지가 잠금(블러) 상태로 보인다. 응답 항목이 담는 presigned URL은 15분
// 만료라 애초에 캐시 대상이 아니기도 하다(apps/web/CLAUDE.md "presigned GET URL … 캐시 금지").
export function useCharacterImageArchiveQuery(characterId: string, enabled: boolean) {
  return useQuery<ImageArchiveItem[], ApiError>({
    queryKey: characterImageArchiveKeys.list(characterId),
    queryFn: async () =>
      (await apiClient.get<ImageArchiveItem[]>(`/characters/${characterId}/image-archive`)).data,
    enabled,
    gcTime: 0,
  });
}
