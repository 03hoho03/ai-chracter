import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { formToServer } from "../model/formToServer";
import type { GenerateImagesFormValues } from "../model/schema";

export type GenerateImageResponse = components["schemas"]["GenerateImageResponse"];

// 인자는 폼값 그대로 받는다(호출부가 `variables.count`로 요청 장수를 읽는다) — 바디 모양 변환은
// `formToServer`가 전담한다.
export function useGenerateImagesMutation() {
  return useMutation({
    mutationFn: (values: GenerateImagesFormValues) =>
      apiClient.post<GenerateImageResponse>("/images/generate", formToServer(values)).then((res) => res.data),
  });
}
