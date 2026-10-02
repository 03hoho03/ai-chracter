import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { llmUsageKeys } from "./keys";

export type AdminLlmUsageResponse = components["schemas"]["AdminLlmUsageResponse"];
export type AdminLlmUsageRow = components["schemas"]["AdminLlmUsageRow"];

/** from/to(YYYY-MM-DD, KST 날짜)의 LLM 호출 집계. 기간은 서버가 92일까지만 받는다. */
export function useLlmUsageQuery(params: { from: string; to: string }) {
  return useQuery<AdminLlmUsageResponse, ApiError>({
    queryKey: llmUsageKeys.range(params),
    // 400 은 기간이 잘못된 것(역순·92일 초과)이라 다시 보내도 같다 — 기본 재시도 3회면 안내가 몇 초 늦게 뜬다.
    retry: (failureCount, error) => error.status !== 400 && failureCount < 3,
    queryFn: async () =>
      (
        await apiClient.get<AdminLlmUsageResponse>("/admin/llm-usage", {
          params: { from: params.from, to: params.to },
        })
      ).data,
  });
}
