import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import type { NovelChapterModelId } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

export type NovelChapterProposal = components["schemas"]["NovelChapterProposalResponse"];
export type NovelChapterCandidate = components["schemas"]["NovelChapterCandidate"];

type ChapterProposalVariables = { novelId: string; model: NovelChapterModelId };

/** `POST /novels/{novelId}/chapter-proposal` — 고른 모델로 다음 화들의 끝으로 고를 수 있는 턴 목록과 AI 의 제안
 * 하나. 모델마다 한 번에 담을 수 있는 턴 수가 달라 후보 목록·제안·후보별 화 수와 금액이 모델을 따라 바뀐다 — 그래서
 * 모델을 바꾸면 다시 부른다(부를 때마다 시간당 제안 상한에 센다). 과금이 없고 동기다. 제안을 만들지 못해도 200 +
 * `suggestion: null` 이라 목록만으로 고를 수 있다. 쓰고 나면 버리는 값이라 캐시에 두지 않는다(같은 소설이라도 대화가
 * 이어지면 후보가 바뀐다). */
export function useChapterProposalMutation() {
  return useMutation<NovelChapterProposal, ApiError, ChapterProposalVariables>({
    mutationFn: async ({ novelId, model }) =>
      (await apiClient.post<NovelChapterProposal>(`/novels/${novelId}/chapter-proposal`, { model })).data,
  });
}
