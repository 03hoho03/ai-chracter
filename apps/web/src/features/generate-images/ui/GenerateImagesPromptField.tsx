import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useFormContext } from "react-hook-form";

import type { GenerateImagesFormValues } from "../model/schema";
import { useGenerateImagesSubmit } from "../model/useGenerateImagesSubmit";

// image-refact-goal-prompt.md IR-15 — danbooru 태그 예시(품질 부스터 금지, LG-3이 서버에서 치운
// Animagine 시그니처 문구라 FE 번들에도 넣지 않는다).
const PROMPT_PLACEHOLDER =
  "1girl, solo, long hair, school uniform, cherry blossoms, looking at viewer, upper body";

// image-refact-techspec.md IT-9 — `<form>` 엘리먼트는 이 조각(중앙 열)이 감싼다. FormProvider는
// React context라 DOM 위치와 무관하므로, 다른 열/시트의 필드도 이 제출에 포함된다.
export function GenerateImagesPromptField() {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useFormContext<GenerateImagesFormValues>();
  const { onSubmit, isModelsPending } = useGenerateImagesSubmit();

  return (
    <form
      className="flex flex-col gap-6"
      noValidate
      // `handleSubmit`은 프라미스를 반환하는데 이 속성은 void를 기대한다(no-misused-promises).
      onSubmit={(event) => void handleSubmit(onSubmit)(event)}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="generate-images-prompt">프롬프트</Label>
        {/* 브라우저 실검증(S6) — 프롬프트와 제출 버튼을 한 보더 박스에 묶는다(크랙 실측: 박스 안
            우하단 버튼). 포커스 링은 안쪽 Textarea가 아니라 이 박스가 받아야 하므로
            `has-[textarea:focus-visible]:`로 하우스 레시피(DESIGN.md §Buttons Focus)를 얹는다 —
            안쪽 Textarea의 자기 보더·링은 아래에서 지운다(이중 보더 방지). */}
        <div className="flex flex-col gap-2 rounded-lg border border-input bg-background p-2 has-[textarea:focus-visible]:border-ring has-[textarea:focus-visible]:ring-3 has-[textarea:focus-visible]:ring-ring/50">
          <Textarea
            id="generate-images-prompt"
            placeholder={PROMPT_PLACEHOLDER}
            rows={4}
            aria-invalid={!!errors.prompt}
            aria-describedby={errors.prompt ? "generate-images-prompt-error" : undefined}
            className="border-0 bg-transparent p-0 focus-visible:ring-0"
            {...register("prompt")}
          />
          <div className="flex justify-end">
            {/* 모델 목록이 아직 로딩 중이면 model/style이 비어 있어 제출해도 zod가 조용히 막는다(그
                필드엔 에러 텍스트 UI가 없다) — 누를 게 없는 상태를 숨기지 않고 버튼을 함께 잠근다. */}
            <Button type="submit" disabled={isSubmitting || isModelsPending}>
              이미지 생성
            </Button>
          </div>
        </div>
        {errors.prompt && (
          <p id="generate-images-prompt-error" role="alert" className="text-xs text-destructive-text">
            {errors.prompt.message}
          </p>
        )}
      </div>
    </form>
  );
}
