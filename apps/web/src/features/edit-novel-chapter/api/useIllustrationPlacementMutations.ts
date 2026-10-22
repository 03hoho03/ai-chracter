import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { writeNovelChapterRevision, type NovelChapterResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

import type { PlacementTarget } from "../model/boardIllustrations";

type PlacementVariables = {
  novelId: string;
  chapterId: string;
  /** 그 판의 배치 id. 판마다 새로 매겨지므로 기준 판과 같은 응답에서 온 것이어야 한다. */
  illustrationId: string;
  /** 보고 있던 판. 그사이 다른 곳에서 새 판이 생겼으면 서버가 409 로 막는다. */
  baseRevisionId: string;
};

/** `POST …/illustrations/{id}/move` — 배치 하나를 다른 문단 앞·뒤로 옮긴다(위치 확인 필요인 그림을 다시 놓을 때도). 순서를
 * 비워 보내 그 자리 맨 끝으로 간다. 글이 같은 새 판(201 + 장 전체)이 생기고, 그 응답으로 캐시를 바로 쓴다. 무과금이다. */
export function useMoveIllustrationMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelChapterResponse, ApiError, PlacementVariables & { target: PlacementTarget }>({
    mutationFn: async ({ novelId, chapterId, illustrationId, baseRevisionId, target }) =>
      (
        await apiClient.post<NovelChapterResponse>(
          `/novels/${novelId}/chapters/${chapterId}/illustrations/${illustrationId}/move`,
          { baseRevisionId, anchorBlockId: target.anchorBlockId, placement: target.placement },
        )
      ).data,
    onSuccess: (chapter) => writeNovelChapterRevision(queryClient, chapter),
  });
}

/** `POST …/illustrations/{id}/detach` — 배치 하나를 뗀다. 그림 파일은 지우지 않고(앞 판이 여전히 쓴다) 판 이력에서 되돌릴 수
 * 있다. 생성 이미지 사용처는 지난 판까지 세므로 떼어도 바뀌지 않아 그 목록은 다시 받지 않는다. */
export function useDetachIllustrationMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelChapterResponse, ApiError, PlacementVariables>({
    mutationFn: async ({ novelId, chapterId, illustrationId, baseRevisionId }) =>
      (
        await apiClient.post<NovelChapterResponse>(
          `/novels/${novelId}/chapters/${chapterId}/illustrations/${illustrationId}/detach`,
          { baseRevisionId },
        )
      ).data,
    onSuccess: (chapter) => writeNovelChapterRevision(queryClient, chapter),
  });
}
