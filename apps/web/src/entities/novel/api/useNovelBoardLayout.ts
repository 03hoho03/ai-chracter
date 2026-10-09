import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";

export type NovelBoardLayout = components["schemas"]["NovelBoardLayout"];
export type NovelBoardPosition = components["schemas"]["NovelBoardPosition"];
export type NovelBoardViewport = components["schemas"]["NovelBoardViewport"];

/** `GET /novels/{novelId}/board-layout` — 저장한 편집 보드 배치(저장한 적 없으면 `null`). 지금 없는 화·인물의 자리는
 * 서버가 빼고 준다. 실패해도 보드는 자동 배치로 그리면 되므로(다음 저장이 덮는다) 호출부가 오류를 띄우지 않는다. */
export function useNovelBoardLayoutQuery(novelId: string) {
  return useQuery<NovelBoardLayout | null, ApiError>({
    queryKey: novelKeys.boardLayout(novelId),
    queryFn: async () =>
      (await apiClient.get<components["schemas"]["NovelBoardLayoutResponse"]>(`/novels/${novelId}/board-layout`)).data
        .layout,
  });
}

/** `PUT /novels/{novelId}/board-layout` — 배치를 통째로 저장한다(204). 보낸 배치를 그대로 캐시에 쓴다 — 응답 본문이
 * 없고, 다시 받게 두면 보드를 떠났다 돌아올 때 저장 전 배치가 먼저 그려져 카드가 한 번 튄다. `viewport` 는 서버
 * 칸에 기본값이 없어 화면 위치를 모르면 `null` 을 담아 보낸다(빠지면 422). 크기가 상세 `limits.boardLayoutMaxBytes` 를
 * 넘으면 422 `NOVEL_BOARD_LAYOUT_TOO_LARGE`. */
export function useSaveNovelBoardLayoutMutation() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, { novelId: string; layout: NovelBoardLayout }>({
    mutationFn: async ({ novelId, layout }) => {
      await apiClient.put(`/novels/${novelId}/board-layout`, layout);
    },
    onSuccess: (_, { novelId, layout }) => {
      queryClient.setQueryData<NovelBoardLayout | null>(novelKeys.boardLayout(novelId), layout);
    },
  });
}
