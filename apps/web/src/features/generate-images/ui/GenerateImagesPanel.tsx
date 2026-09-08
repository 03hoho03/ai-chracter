import { useState } from "react";
import { toast } from "sonner";

import { useImageJobStatusQuery } from "@/entities/image-job";
import { isApiError } from "@/shared/lib/api/client";

import { useGenerateImagesMutation } from "../api/useGenerateImagesMutation";
import type { GenerateImagesFormValues } from "../model/schema";
import { GenerateImagesForm } from "./GenerateImagesForm";
import { GenerateImagesResultGrid } from "./GenerateImagesResultGrid";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

// US-008 — GenerateImagesForm(순수 폼)과 잡 폴링·결과 그리드를 조합한다. 페이지는 이 컴포넌트만 배치한다.
//
// 생성 실패는 별도 에러 state가 아니라 토스트로 낸다(FORM-06이 에러 useState를 금지하고 FORM-08이
// 필드에 못 붙는 에러의 출구로 토스트를 명시한다). `useForm`은 자식 `GenerateImagesForm` 안에 있어
// 여기서 `setError("root")`를 칠 폼 인스턴스가 없다 — 배너를 되살리려면 메시지를 자식에게 내려
// 자식이 root 에러를 치는 구조가 돼야 한다.
export function GenerateImagesPanel() {
  const [jobId, setJobId] = useState<string | null>(null);

  const generateMutation = useGenerateImagesMutation();
  const jobQuery = useImageJobStatusQuery(jobId ?? "", jobId !== null);

  async function handleSubmit(values: GenerateImagesFormValues) {
    setJobId(null);
    try {
      const response = await generateMutation.mutateAsync(values);
      setJobId(response.jobId);
    } catch (error) {
      const apiError = isApiError(error) ? error : null;
      toast.error(apiError?.status === 422 ? "입력값을 다시 확인해주세요." : GENERIC_ERROR_MESSAGE);
    }
  }

  return (
    <div className="flex flex-col gap-8">
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
