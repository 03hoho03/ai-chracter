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
  IMAGE_ASPECT_RATIO_OPTIONS,
  IMAGE_COUNT_OPTIONS,
  IMAGE_STYLE_PRESET_OPTIONS,
  generateImagesDefaultValues,
  generateImagesSchema,
  type GenerateImagesFormValues,
} from "../model/schema";

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

      <Button type="submit" className="self-start" disabled={isSubmitting}>
        이미지 생성
      </Button>
    </form>
  );
}
