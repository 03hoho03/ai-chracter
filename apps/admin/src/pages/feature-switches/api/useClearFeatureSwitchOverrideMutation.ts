import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminFeatureSwitchChangeResult } from "../model/types";
import { applySavedSwitch } from "./applySavedSwitch";
import { featureSwitchKeys } from "./keys";

type AdminFeatureSwitchClearRequest = components["schemas"]["AdminFeatureSwitchClearRequest"];

/** 이 화면이 모르는 이름의 덮어쓰기도 지울 수 있어 이름은 문자열이다. */
type ClearVariables = { name: string } & AdminFeatureSwitchClearRequest;

/** 덮어쓰기를 지워 `.env` 값으로 돌린다. 캐시 처리는 바꾸기와 같다. */
export function useClearFeatureSwitchOverrideMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminFeatureSwitchChangeResult, ApiError, ClearVariables>({
    mutationFn: async ({ name, ...payload }) =>
      (
        await apiClient.delete<AdminFeatureSwitchChangeResult>(
          `/admin/feature-switches/${encodeURIComponent(name)}/override`,
          { data: payload },
        )
      ).data,
    onSuccess: (result, { name }) => applySavedSwitch(queryClient, name, result),
    onError: () => void queryClient.invalidateQueries({ queryKey: featureSwitchKeys.all }),
  });
}
