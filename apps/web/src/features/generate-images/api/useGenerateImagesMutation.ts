import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { formToServer } from "../model/formToServer";
import type { GenerateImagesFormValues } from "../model/schema";

export type GenerateImageResponse = components["schemas"]["GenerateImageResponse"];

export type GenerateImagesVariables = {
  values: GenerateImagesFormValues;
  isReferenceEnabled: boolean;
};

// 인자는 폼값 그대로 받는다(호출부가 `variables.values.count`로 요청 장수를 읽는다) — 바디 모양
// 변환은 `formToServer`가 전담한다. 참조를 쓸 수 있는지는 폼 값이 아니라 모델 목록에서 오므로
// 제출 시점의 판정을 함께 받는다.
export function useGenerateImagesMutation() {
  return useMutation({
    mutationFn: ({ values, isReferenceEnabled }: GenerateImagesVariables) =>
      apiClient
        .post<GenerateImageResponse>("/images/generate", formToServer(values, { isReferenceEnabled }))
        .then((res) => res.data),
  });
}
