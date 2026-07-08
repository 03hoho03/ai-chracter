import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { buildPreviewStartState } from "../model/buildPreviewStartState";
import { previewSessionKeys } from "./keys";
import type { PreviewSessionState, PreviewStartPayload } from "./types";

type PreviewSessionStartResponseDto = components["schemas"]["PreviewSessionStartResponse"];

/**
 * techspec-builder-common.md §3 — formToServer(getValues())를 검증 없이 그대로 전송해 미리보기
 * 세션을 시작한다(US-088). `POST /preview-sessions`는 previewSessionId만 반환하므로, 초기 상태
 * (오프닝 메시지/스탯 초기값)는 이미 갖고 있는 같은 payload로부터 buildPreviewStartState가 계산해
 * 캐시를 직접 채운다 — 별도 GET 엔드포인트가 없다(apps/api/CLAUDE.md 참고).
 */
export function useStartPreviewMutation() {
  const queryClient = useQueryClient();

  return useMutation<PreviewSessionState, ApiError, PreviewStartPayload>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post<PreviewSessionStartResponseDto>("/preview-sessions", payload);
      return buildPreviewStartState(data.previewSessionId, payload);
    },
    onSuccess: (state) => {
      queryClient.setQueryData(previewSessionKeys.detail(state.previewSessionId), state);
    },
  });
}
