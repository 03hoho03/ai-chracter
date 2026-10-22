import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { generatedImagesKeys } from "@/entities/generated-image";
import { writeNovelChapterRevision, type NovelChapterResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

import type { AttachRequest, IllustrationSource, PlacementTarget } from "../model/boardIllustrations";

type PlacementVariables = {
  novelId: string;
  chapterId: string;
  /** 그 판의 배치 id. 판마다 새로 매겨지므로 기준 판과 같은 응답에서 온 것이어야 한다. */
  illustrationId: string;
  /** 보고 있던 판. 그사이 다른 곳에서 새 판이 생겼으면 서버가 409 로 막는다. */
  baseRevisionId: string;
};

/** `POST …/illustrations` — 그림 한 장을 지금 판 문단의 앞·뒤에 붙인다. 순서를 비워 보내 그 자리 맨 끝으로 간다. 글이 같은 새
 * 판(201 + 장 전체)이 생기고 그 응답으로 캐시를 바로 쓴다. 내 생성 이미지를 붙였으면 그 이미지의 사용처(이미지 화면의 "사용
 * 중인 곳")가 바뀌므로 생성 이미지 목록도 다시 받게 한다. 무과금이다. */
export function useAttachIllustrationMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelChapterResponse, ApiError, AttachRequest & { novelId: string; chapterId: string }>({
    mutationFn: async ({ novelId, chapterId, baseRevisionId, target, assetId, source }) =>
      (
        await apiClient.post<NovelChapterResponse>(`/novels/${novelId}/chapters/${chapterId}/illustrations`, {
          baseRevisionId,
          anchorBlockId: target.anchorBlockId,
          placement: target.placement,
          assetId,
          source,
        })
      ).data,
    onSuccess: (chapter, { source }) => {
      writeNovelChapterRevision(queryClient, chapter);
      if (source === "generated") void queryClient.invalidateQueries({ queryKey: generatedImagesKeys.list() });
    },
  });
}

/** `POST …/illustrations/{id}/replace` — 배치 하나의 그림만 바꾼다(자리·순서 그대로). 응답이 올 때까지 옛 그림이 그대로 서 있다
 * — 떼고 붙이는 두 요청이 아니라 한 요청이라서다. 새 그림이 내 생성 이미지면 사용처가 바뀌어 그 목록을 다시 받게 한다(빠지는
 * 옛 그림의 사용처는 지난 판까지 세므로 바뀌지 않는다). */
export function useReplaceIllustrationMutation() {
  const queryClient = useQueryClient();

  return useMutation<
    NovelChapterResponse,
    ApiError,
    PlacementVariables & { assetId: string; source: IllustrationSource }
  >({
    mutationFn: async ({ novelId, chapterId, illustrationId, baseRevisionId, assetId, source }) =>
      (
        await apiClient.post<NovelChapterResponse>(
          `/novels/${novelId}/chapters/${chapterId}/illustrations/${illustrationId}/replace`,
          { baseRevisionId, assetId, source },
        )
      ).data,
    onSuccess: (chapter, { source }) => {
      writeNovelChapterRevision(queryClient, chapter);
      if (source === "generated") void queryClient.invalidateQueries({ queryKey: generatedImagesKeys.list() });
    },
  });
}

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
