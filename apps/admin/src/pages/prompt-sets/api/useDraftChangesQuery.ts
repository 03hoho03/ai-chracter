import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { PromptLane } from "../model/lane";
import type { PromptModel } from "../model/model";
import type { AdminPromptDraftChangesResponse } from "../model/semver";
import { promptSetKeys } from "./keys";

/** 게시하면 섹션 판이 어떻게 갈릴지 서버가 계산한 값(읽기만 한다). 응답의 기준판 id·초안 해시를 게시 요청에 그대로 돌려보내야
 * 그 사이 끼어든 게시·저장을 서버가 409 로 잡는다 — 그래서 게시 모달을 열 때마다 새로 받는다(`staleTime: 0`), 모달이
 * 닫혀 있으면 받지 않는다. */
export function useDraftChangesQuery(lane: PromptLane, model: PromptModel, enabled: boolean) {
  return useQuery<AdminPromptDraftChangesResponse, ApiError>({
    queryKey: promptSetKeys.draftChanges(lane, model),
    queryFn: async () =>
      (
        await apiClient.get<AdminPromptDraftChangesResponse>(`/admin/prompt-sets/${lane}/draft/changes`, {
          params: { model },
        })
      ).data,
    enabled,
    staleTime: 0,
  });
}
