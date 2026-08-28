import { useState } from "react";
import type { ApiError } from "@ai-character-chat/api-types";

import { useImageJobStatusQuery } from "../../../entities/image-job";
import { useGenerateImagesMutation } from "../api/useGenerateImagesMutation";
import type { GenerateImagesFormValues } from "../model/schema";
import { GenerateImagesForm } from "./GenerateImagesForm";
import { GenerateImagesResultGrid } from "./GenerateImagesResultGrid";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

// US-008 — GenerateImagesForm(순수 폼)과 잡 폴링·결과 그리드를 조합한다. 페이지는 이 컴포넌트만 배치한다.
export function GenerateImagesPanel() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const generateMutation = useGenerateImagesMutation();
  const jobQuery = useImageJobStatusQuery(jobId ?? "", jobId !== null);

  async function handleSubmit(values: GenerateImagesFormValues) {
    setFormError(null);
    setJobId(null);
    try {
      const response = await generateMutation.mutateAsync(values);
      setJobId(response.jobId);
    } catch (error) {
      const apiError = error as ApiError;
      setFormError(apiError.status === 422 ? "입력값을 다시 확인해주세요." : GENERIC_ERROR_MESSAGE);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      {formError && (
        <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive-text">
          {formError}
        </p>
      )}

      <GenerateImagesForm onSubmit={handleSubmit} />

      {jobId !== null && (
        <GenerateImagesResultGrid
          job={jobQuery.data}
          requestedCount={generateMutation.variables?.count ?? 1}
          isQueryError={jobQuery.isError}
        />
      )}
    </div>
  );
}
