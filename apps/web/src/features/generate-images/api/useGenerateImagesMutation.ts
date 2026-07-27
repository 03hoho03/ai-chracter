import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import type { GenerateImagesFormValues } from "../model/schema";

export type GenerateImageResponse = components["schemas"]["GenerateImageResponse"];

export function useGenerateImagesMutation() {
  return useMutation({
    mutationFn: (values: GenerateImagesFormValues) =>
      apiClient.post<GenerateImageResponse>("/images/generate", values).then((res) => res.data),
  });
}
