import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { novelKeys, type NovelDetailResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

type NovelUpdateRequest = components["schemas"]["NovelUpdateRequest"];
type UpdateNovelInfoVariables = { novelId: string; body: NovelUpdateRequest };

/** `PATCH /novels/{novelId}` — 소설 제목·소개·표지(보낸 칸만). 응답이 상세 전체라 그것으로 상세 캐시를 바로 덮는다 —
 * 다시 받게 두면 저장 직후 옛 제목이 한 번 칠해진다. 목록에도 제목·표지가 실려 목록은 낡았다고 표시한다. 노벨 공개
 * 상태도 다시 받는다 — 공개본과 제목·소개를 견주는 값이라, 같은 작품 정보 화면의 "노벨 공개" 절이 "다시 공개하기"를
 * 바로 보이게.
 *
 * 표지는 `coverAssetId` 에 `null` 을 보내면 원작 썸네일로 되돌리고, 칸을 아예 빼면 그대로 둔다 — 그래서 바꾸지 않는
 * 칸은 `undefined` 로 두지 말고 빼서 보낸다(서버가 `null` 과 부재를 가른다). */
export function useUpdateNovelInfoMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelDetailResponse, ApiError, UpdateNovelInfoVariables>({
    mutationFn: async ({ novelId, body }) => (await apiClient.patch<NovelDetailResponse>(`/novels/${novelId}`, body)).data,
    onSuccess: (novel) => {
      queryClient.setQueryData(novelKeys.detail(novel.id), novel);
      void queryClient.invalidateQueries({ queryKey: novelKeys.list() });
      void queryClient.invalidateQueries({ queryKey: novelKeys.publication(novel.id) });
    },
  });
}
