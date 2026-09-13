import { useState } from "react";
import { toast } from "sonner";

import { useImageJobStatusQuery } from "@/entities/image-job";
import { isApiError } from "@/shared/api/client";

import { useGenerateImagesMutation } from "../api/useGenerateImagesMutation";
import type { GenerateImagesFormValues } from "../model/schema";
import { GenerateImagesFormProvider } from "./GenerateImagesFormProvider";
import { GenerateImagesOptionsFields } from "./GenerateImagesOptionsFields";
import { GenerateImagesPromptField } from "./GenerateImagesPromptField";
import { GenerateImagesResultGrid } from "./GenerateImagesResultGrid";
import { GenerateImagesStyleGrid } from "./GenerateImagesStyleGrid";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

// US-008 — 잡 폴링·결과 그리드는 그대로, 폼만 image-refact-techspec.md IT-9로 세 조각(Prompt/Style/
// Options)에 쪼개졌다. 이 패널이 그 세 조각을 한 열로 쌓아 pages/studio-images가 쓰던 기존 화면을
// 재현한다 — widgets/image-studio(3열 셸)가 다음 런에서 조각을 각 열에 나눠 배치한다.
//
// 생성 실패는 별도 에러 state가 아니라 토스트로 낸다(FORM-06이 에러 useState를 금지하고 FORM-08이
// 필드에 못 붙는 에러의 출구로 토스트를 명시한다). `useForm`은 GenerateImagesFormProvider 안에 있어
// 여기서 `setError("root")`를 칠 폼 인스턴스가 없다 — 배너를 되살리려면 메시지를 내려 그쪽이 root
// 에러를 치는 구조가 돼야 한다.
export function GenerateImagesPanel() {
  const [jobId, setJobId] = useState<string | undefined>(undefined);

  const generateMutation = useGenerateImagesMutation();
  const jobQuery = useImageJobStatusQuery(jobId ?? "", jobId !== undefined);

  async function handleSubmit(values: GenerateImagesFormValues) {
    setJobId(undefined);
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
      <GenerateImagesFormProvider onSubmit={handleSubmit}>
        <div className="flex flex-col gap-6">
          <GenerateImagesPromptField />
          <GenerateImagesStyleGrid />
          <GenerateImagesOptionsFields />
        </div>
      </GenerateImagesFormProvider>

      {jobId !== undefined && (
        <GenerateImagesResultGrid
          job={jobQuery.data}
          requestedCount={generateMutation.variables?.count ?? 1}
          isQueryError={jobQuery.isError}
        />
      )}
    </div>
  );
}
