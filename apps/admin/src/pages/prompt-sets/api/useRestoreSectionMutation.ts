import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { PromptLane } from "../model/lane";
import type { AdminPromptDraftResponse } from "../model/schema";
import { promptSetKeys } from "./keys";

type AdminPromptSectionRestoreRequest = components["schemas"]["AdminPromptSectionRestoreRequest"];

type RestoreSectionVariables = AdminPromptSectionRestoreRequest & {
  id: string;
  /** 채널 하나 또는 화자 라벨 묶음. */
  section: string;
};

/** 옛 게시본의 섹션 하나만 그 체인 초안으로 가져온다(게시하지 않는다). 응답이 새 초안 전체라 통째 복원과 같이 초안 캐시를 바로
 * 채우고, 체인의 모델은 응답의 `model`(= 원본 세트의 모델)을 쓴다 — 서버가 실제로 쓴 체인과 어긋나지 않게. 가져온 섹션은 다음
 * 게시에서 바뀐 섹션으로 잡히므로 바뀐 섹션 목록도 무효화한다. */
export function useRestoreSectionMutation(lane: PromptLane) {
  const queryClient = useQueryClient();
  return useMutation<AdminPromptDraftResponse, ApiError, RestoreSectionVariables>({
    mutationFn: async ({ id, section, overwriteDraftChanges }) =>
      (
        await apiClient.post<AdminPromptDraftResponse>(
          `/admin/prompt-sets/${id}/sections/${encodeURIComponent(section)}/restore`,
          { overwriteDraftChanges } satisfies AdminPromptSectionRestoreRequest,
        )
      ).data,
    onSuccess: (data) => {
      queryClient.setQueryData(promptSetKeys.draft(lane, data.model), data);
      void queryClient.invalidateQueries({ queryKey: promptSetKeys.preview(lane, data.model) });
      void queryClient.invalidateQueries({ queryKey: promptSetKeys.draftChanges(lane, data.model) });
    },
  });
}
