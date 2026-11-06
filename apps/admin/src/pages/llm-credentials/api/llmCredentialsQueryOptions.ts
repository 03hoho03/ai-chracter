import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminLlmCredentialListResponse } from "../model/credential";
import { llmCredentialKeys } from "./keys";

/** 목록 전체(위치 순)와 목록 상태. 창 포커스 재조회 기본값을 그대로 둔다 — 소진은 서버 런타임이 바꾸는 상태라, 운영자가 알림을 보고
 * 돌아오면 바로 새 값이 보이는 편이 맞다. */
export const llmCredentialsQueryOptions = queryOptions({
  queryKey: llmCredentialKeys.list(),
  queryFn: async () => (await apiClient.get<AdminLlmCredentialListResponse>("/admin/llm-credentials")).data,
});
