import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";

export type NovelChainEstimate = components["schemas"]["NovelChainEstimate"];

/** `GET /novels/{novelId}/chain-estimate` — "남은 대화 한 번에"의 모델별 견적(묶음 수·최대 화 수·금액). 한 번에 모든
 * 모델이 오므로 모델을 바꿔도 다시 묻지 않는다. 대화가 이어지면 값이 바뀌어 확인 화면을 열 때마다 새로 받는다
 * (`staleTime` 0, 화 생성이 끝날 때 `novelKeys.all` 무효화에도 든다). 만들 턴이 없으면 409 `NOVEL_NOTHING_NEW` 라
 * 호출부는 실패를 "연쇄 선택지 없음"으로 읽는다. `isEnabled` 가 거짓이면 묻지 않는다. */
export function useNovelChainEstimateQuery(novelId: string, isEnabled: boolean) {
  return useQuery<NovelChainEstimate[], ApiError>({
    queryKey: novelKeys.chainEstimate(novelId),
    queryFn: async () =>
      (await apiClient.get<components["schemas"]["NovelChainEstimateResponse"]>(`/novels/${novelId}/chain-estimate`))
        .data.options,
    enabled: isEnabled,
    retry: false,
  });
}
