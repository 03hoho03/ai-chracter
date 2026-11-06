import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminLlmCredential, AdminLlmCredentialCreateRequest } from "../model/credential";
import { invalidateCredentials, reloadIfListStale } from "./cache";

/**
 * 추가. 새 항목은 꺼진 채 목록 끝에 들어온다.
 *
 * 요청 변수(키 원문)는 뮤테이션 상태에 남는다. `gcTime: 0` 이면 관찰자가 빠지는 순간(대화상자가 닫히면) 다음 틱에 버려지고, 열린 채
 * 실패하면 관찰자가 남아 버려지지 않으므로 부르는 쪽이 제출 처리가 끝날 때마다 `reset()` 으로 관찰자를 뗀다. `networkMode: "always"` 는
 * 오프라인에서 키를 쥔 채 일시정지했다가 연결이 돌아오면 운영자가 모르는 사이 보내는 길을 없앤다 — 바로 실패한다.
 *
 * 목록 판이 올랐는데 항목 응답에는 판이 없어 목록을 다시 받는다. 그 재조회를 돌려줘 끝날 때까지 이 뮤테이션을 진행 중으로 둔다 —
 * 그동안 목록이 다시 오는 중이라 순서 버튼이 잠긴다.
 */
export function useCreateCredentialMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminLlmCredential, ApiError, AdminLlmCredentialCreateRequest>({
    mutationFn: async (body) => (await apiClient.post<AdminLlmCredential>("/admin/llm-credentials", body)).data,
    gcTime: 0,
    networkMode: "always",
    onSuccess: () => invalidateCredentials(queryClient),
    onError: (error) => reloadIfListStale(queryClient, error),
  });
}
