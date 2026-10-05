import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

export type NovelChapterProposal = components["schemas"]["NovelChapterProposalResponse"];
export type NovelChapterCandidate = components["schemas"]["NovelChapterCandidate"];

/** `POST /novels/{novelId}/chapter-proposal` — 다음 장 끝으로 고를 수 있는 턴 목록과 AI 의 제안 하나. 과금이 없고
 * 동기다. 제안을 만들지 못해도 200 + `suggestion: null` 이라 목록만으로 고를 수 있다. 쓰고 나면 버리는 값이라
 * 캐시에 두지 않는다(같은 소설이라도 대화가 이어지면 후보가 바뀐다). */
export function useChapterProposalMutation() {
  return useMutation<NovelChapterProposal, ApiError, string>({
    mutationFn: async (novelId) =>
      (await apiClient.post<NovelChapterProposal>(`/novels/${novelId}/chapter-proposal`)).data,
  });
}
