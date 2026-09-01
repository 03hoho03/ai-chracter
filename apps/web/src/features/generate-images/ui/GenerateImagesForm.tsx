import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm, useWatch } from "react-hook-form";

import { useImageModelsQuery } from "@/entities/image-model";
import {
  IMAGE_GENERATION_SUSPENDED_NOTICE,
  IS_IMAGE_GENERATION_SUSPENDED,
} from "../model/availability";
import {
  IMAGE_ASPECT_RATIO_OPTIONS,
  IMAGE_COUNT_OPTIONS,
  IMAGE_STYLE_PRESET_OPTIONS,
  generateImagesDefaultValues,
  generateImagesSchema,
  type GenerateImagesFormValues,
} from "../model/schema";

const SUSPENDED_NOTICE_ID = "generate-images-suspended-notice";

type GenerateImagesFormProps = {
  onSubmit: (values: GenerateImagesFormValues) => void | Promise<void>;
}

export function GenerateImagesForm({ onSubmit }: GenerateImagesFormProps) {
  const { data: models, isPending: isModelsPending } = useImageModelsQuery();
  const {
    register,
    handleSubmit,
    control,
    setValue,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<GenerateImagesFormValues>({
    resolver: zodResolver(generateImagesSchema),
    defaultValues: generateImagesDefaultValues,
  });

  const selectedModelId = useWatch({ control, name: "model" });
  const selectedModel = models?.find((model) => model.id === selectedModelId);
  const supportedRatios = new Set<string>(
    selectedModel?.supportedAspectRatios ?? IMAGE_ASPECT_RATIO_OPTIONS.map((option) => option.value),
  );
  const isRatioRestricted =
    selectedModel != null &&
    selectedModel.supportedAspectRatios.length < IMAGE_ASPECT_RATIO_OPTIONS.length;

  // 모델을 바꿨을 때 현재 선택한 비율을 그 모델이 지원하지 않으면, 지원하는 첫 비율로 옮긴다.
  const handleModelChange = (nextModelId: string, onChange: (value: string) => void) => {
    onChange(nextModelId);
    const nextModel = models?.find((model) => model.id === nextModelId);
    if (nextModel == null) return;
    if (!nextModel.supportedAspectRatios.includes(getValues("aspectRatio"))) {
      const [firstSupported] = nextModel.supportedAspectRatios;
      if (firstSupported != null) setValue("aspectRatio", firstSupported);
    }
  };

  return (
    <form
      className="flex flex-col gap-6"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        // 제출 버튼이 `disabled`가 아니라 `aria-disabled`라 포커스가 남고, 포커스가 남으면
        // Enter가 실제로 여기까지 온다(`pointer-events-none`은 포인터만 막는다). 중단 중에는
        // 여기서 한 번 더 끊어야 키보드로 잡이 걸리지 않는다 — `ContentListLoadMore`와 같은 짝.
        if (IS_IMAGE_GENERATION_SUSPENDED) return;
        void handleSubmit(onSubmit)(event);
      }}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="generate-images-prompt">프롬프트</Label>
        <Textarea
          id="generate-images-prompt"
          placeholder="생성하고 싶은 이미지를 설명해주세요"
          rows={4}
          aria-invalid={!!errors.prompt}
          aria-describedby={errors.prompt ? "generate-images-prompt-error" : undefined}
          {...register("prompt")}
        />
        {errors.prompt && (
          <p id="generate-images-prompt-error" role="alert" className="text-xs text-destructive-text">
            {errors.prompt.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="generate-images-model">모델</Label>
        <Controller
          control={control}
          name="model"
          render={({ field }) => (
            <Select
              value={field.value}
              onValueChange={(value) => handleModelChange(value, field.onChange)}
              disabled={isModelsPending}
            >
              <SelectTrigger id="generate-images-model" className="w-full">
                <SelectValue placeholder="모델 불러오는 중…" />
              </SelectTrigger>
              <SelectContent>
                {models?.map((model) => (
                  <SelectItem key={model.id} value={model.id}>
                    {model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="generate-images-style">스타일</Label>
          <Controller
            control={control}
            name="style"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="generate-images-style" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {IMAGE_STYLE_PRESET_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="generate-images-aspect-ratio">비율</Label>
          <Controller
            control={control}
            name="aspectRatio"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="generate-images-aspect-ratio" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {IMAGE_ASPECT_RATIO_OPTIONS.map((option) => (
                    <SelectItem
                      key={option.value}
                      value={option.value}
                      disabled={!supportedRatios.has(option.value)}
                    >
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
          {isRatioRestricted && (
            <p className="text-xs text-muted-foreground">이 모델이 지원하는 비율만 선택할 수 있어요</p>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="generate-images-count">개수</Label>
          <Controller
            control={control}
            name="count"
            render={({ field }) => (
              <Select
                value={String(field.value)}
                onValueChange={(value) => field.onChange(Number(value))}
              >
                <SelectTrigger id="generate-images-count" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {IMAGE_COUNT_OPTIONS.map((count) => (
                    <SelectItem key={count} value={String(count)}>
                      {count}장
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </div>
      </div>

      {/* 중단 중에는 버튼을 `disabled`가 아니라 `aria-disabled`로 죽인다 — `disabled`면 브라우저가
          포커스 순회에서 통째로 빼서 "왜 못 누르는지"가 키보드·스크린리더에 영영 닿지 않는다
          (`packages/ui/CLAUDE.md`의 드롭다운 항목 처방과 같은 이유, 흐림 65%도 그 값 그대로).
          사유는 버튼 옆에 두고 `aria-describedby`로 묶어 보이는 자리와 접근성 트리를 일치시킨다. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Button
          type="submit"
          disabled={isSubmitting}
          aria-disabled={IS_IMAGE_GENERATION_SUSPENDED || undefined}
          aria-describedby={IS_IMAGE_GENERATION_SUSPENDED ? SUSPENDED_NOTICE_ID : undefined}
          className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
        >
          이미지 생성
        </Button>
        {IS_IMAGE_GENERATION_SUSPENDED && (
          <p id={SUSPENDED_NOTICE_ID} className="min-w-0 text-sm break-keep text-muted-foreground">
            {IMAGE_GENERATION_SUSPENDED_NOTICE}
          </p>
        )}
      </div>
    </form>
  );
}
