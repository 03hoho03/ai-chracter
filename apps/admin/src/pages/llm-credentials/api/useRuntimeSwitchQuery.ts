import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminFeatureSwitchListResponse } from "../model/credential";
import { llmCredentialKeys } from "./keys";

/** 런타임이 목록을 쓰는지 정하는 서버 env 스위치. 어드민에서 바꿀 수 없는 읽기 전용 칸이다. */
const RUNTIME_SWITCH_NAME =
  "llm_credential_pool_enabled" satisfies AdminFeatureSwitchListResponse["readOnly"][number]["name"];

/**
 * 서버 스위치 값. 기능 스위치 조회의 읽기 전용 칸에서 꺼낸다 — 그 값은 응답한 API 프로세스의 env 라 서버 env 를 바꾸고 다시 띄워야만
 * 바뀌고, 기능 스위치 화면의 저장은 이 칸을 바꾸지 않아 재조회 기본값으로 충분하다. 그 칸이 없는 옛 서버면 `undefined` 다(대기·실패와
 * 함께 실효 경로를 "알 수 없음"으로 둔다).
 */
export function useRuntimeSwitchQuery() {
  return useQuery({
    queryKey: llmCredentialKeys.runtimeSwitch(),
    queryFn: async () => (await apiClient.get<AdminFeatureSwitchListResponse>("/admin/feature-switches")).data,
    select: (data) => data.readOnly.find((item) => item.name === RUNTIME_SWITCH_NAME)?.value,
  });
}
