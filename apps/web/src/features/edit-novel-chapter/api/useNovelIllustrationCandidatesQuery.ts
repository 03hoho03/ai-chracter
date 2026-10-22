import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { novelKeys } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

export type NovelIllustrationCandidate = components["schemas"]["NovelOriginalIllustrationCandidate"];

/** `GET /novels/{id}/illustration-candidates` — 이 소설에 붙일 수 있는 원작 그림. 작가가 그 작품에서 본 그림(원작자 본인이면
 * 지금 발행본의 그림 전부)이고, 원작을 그 작가에게 열 수 없으면 빈 목록이다. 창을 열 때만 묻고, 작가가 원작 방에서 그림을
 * 새로 보면 늘어나므로 열 때마다 새로 받는다. 주소가 서명 주소라 닫으면 캐시를 버린다. */
export function useNovelIllustrationCandidatesQuery(novelId: string, enabled: boolean) {
  return useQuery<NovelIllustrationCandidate[], ApiError>({
    queryKey: novelKeys.illustrationCandidates(novelId),
    queryFn: async () =>
      (
        await apiClient.get<components["schemas"]["NovelOriginalIllustrationCandidates"]>(
          `/novels/${novelId}/illustration-candidates`,
        )
      ).data.items,
    enabled,
    gcTime: 0,
  });
}
