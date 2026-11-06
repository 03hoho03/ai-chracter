import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminFeatureSwitchChangeResult, FeatureSwitchName } from "../model/types";
import { applySavedSwitch } from "./applySavedSwitch";
import { featureSwitchKeys } from "./keys";

type AdminFeatureSwitchSetRequest = components["schemas"]["AdminFeatureSwitchSetRequest"];

type SetVariables = { name: FeatureSwitchName } & AdminFeatureSwitchSetRequest;

/** 덮어쓰기를 `value` 로 바꾼다. `expectedOverride` 는 화면이 본 지금 덮어쓰기라, 그새 다른 저장이 있었으면 409 로 돌아온다.
 * 실패하면 목록·이력을 다시 받는다 — 낡은 값 때문의 거절이거나, 응답만 끊기고 저장은 됐을 수 있다. */
export function useSetFeatureSwitchMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminFeatureSwitchChangeResult, ApiError, SetVariables>({
    mutationFn: async ({ name, ...payload }) =>
      (await apiClient.put<AdminFeatureSwitchChangeResult>(`/admin/feature-switches/${name}`, payload)).data,
    onSuccess: (result, { name }) => applySavedSwitch(queryClient, name, result),
    onError: () => void queryClient.invalidateQueries({ queryKey: featureSwitchKeys.all }),
  });
}
