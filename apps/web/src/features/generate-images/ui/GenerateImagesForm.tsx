import { useEffect, useRef } from "react";
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
  generateImagesDefaultValues,
  generateImagesSchema,
  type GenerateImagesFormValues,
} from "../model/schema";
import { GenerateImagesUnavailableState } from "./GenerateImagesUnavailableState";

type GenerateImagesFormProps = {
  onSubmit: (values: GenerateImagesFormValues) => void | Promise<void>;
}

export function GenerateImagesForm({ onSubmit }: GenerateImagesFormProps) {
  const {
    data: models,
    isPending: isModelsPending,
    isError: isModelsError,
    refetch: refetchModels,
  } = useImageModelsQuery();
  const {
    register,
    handleSubmit,
    control,
    setValue,
    getValues,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<GenerateImagesFormValues>({
    resolver: zodResolver(generateImagesSchema),
    defaultValues: generateImagesDefaultValues,
  });

  const selectedModelId = useWatch({ control, name: "model" });

  // model/style 기본값은 스키마에 없다(LT-9) — 목록이 처음 로드되면 첫 가용 모델/스타일로 한 번만
  // reset()한다. 이후 배경 refetch에서는(가용성이 바뀌어도) 다시 손대지 않는다 — 사용자가 이미 고른
  // 값을 조용히 되돌리면 그게 더 놀랍다(LT-9b, `reset()` 선례가 이 저장소에 없어 새로 만든 흐름).
  const hasAppliedModelDefaultsRef = useRef(false);
  useEffect(() => {
    if (hasAppliedModelDefaultsRef.current || models === undefined) return;
    const firstAvailable = models.find((model) => model.available);
    if (firstAvailable == null) return;
    hasAppliedModelDefaultsRef.current = true;
    // styles[0]은 레지스트리 순서에 기대는 것이라 스타일이 여럿이고 그중 앞쪽이 available: false면
    // 깨진다 — 가용한 첫 스타일을 명시적으로 찾는다.
    reset({
      ...getValues(),
      model: firstAvailable.id,
      style: firstAvailable.styles.find((style) => style.available)?.id ?? "",
    });
  }, [models, getValues, reset]);

  // 배경 refetch 실패(staleTime 30s + refetchOnWindowFocus 기본값)에도 query-core의 'error' reducer는
  // 이전 data를 지우지 않는다 — 그래서 models가 남아 있으면(낡았어도) 화면을 갈아엎지 않고 폼을 그대로
  // 보여준다. LG-8("사전 헬스체크 + 즉시 실패")과 모순되지 않는다: 로컬 비가동은 *성공한* 쿼리가
  // `available: false`를 실어 오는 값이라 아래 unavailable 분기가 잡는다. 여기는 쿼리 자체가 실패해
  // "그런지 아닌지도 모른다"이고, 그건 보여줄 게 없을 때만 화면을 대체할 가치가 있다.
  if (isModelsError && models === undefined) {
    return <GenerateImagesUnavailableState reason="error" onRetry={() => void refetchModels()} />;
  }

  const availableModels = models?.filter((model) => model.available) ?? [];

  // (LG-17) models 쿼리의 선행 갭 — 빈 목록과 전 모델 일시 불가는 전에는 "활성화된 빈 Select + 낡은
  // 기본값 + 제출 가능"으로 조용히 깨졌다. 둘 다 제출 이전 상태로 이름을 준다.
  if (models !== undefined && models.length === 0) {
    return <GenerateImagesUnavailableState reason="empty" />;
  }
  if (models !== undefined && availableModels.length === 0) {
    return <GenerateImagesUnavailableState reason="unavailable" onRetry={() => void refetchModels()} />;
  }

  const selectedModel = models?.find((model) => model.id === selectedModelId);
  const supportedRatios = new Set<string>(
    selectedModel?.supportedAspectRatios ?? IMAGE_ASPECT_RATIO_OPTIONS.map((option) => option.value),
  );
  const isRatioRestricted =
    selectedModel != null &&
    selectedModel.supportedAspectRatios.length < IMAGE_ASPECT_RATIO_OPTIONS.length;
  const styleOptions = selectedModel?.styles ?? [];
  const hasUnavailableModel = models?.some((model) => !model.available) ?? false;

  // 모델을 바꿨을 때 현재 선택한 비율/스타일을 그 모델이 지원하지 않으면, 지원하는 첫 값으로 옮긴다.
  const handleModelChange = (nextModelId: string, onChange: (value: string) => void) => {
    onChange(nextModelId);
    const nextModel = models?.find((model) => model.id === nextModelId);
    if (nextModel == null) return;
    if (!nextModel.supportedAspectRatios.includes(getValues("aspectRatio"))) {
      const [firstSupported] = nextModel.supportedAspectRatios;
      if (firstSupported != null) setValue("aspectRatio", firstSupported);
    }
    if (!nextModel.styles.some((style) => style.id === getValues("style"))) {
      // styles[0]은 레지스트리 순서 의존이라 같은 이유로 고친다 — 지금은 모델이 v1 하나뿐이라
      // 이 분기 자체가 도달 불가(모델 전환이 없다)지만, 같은 식을 반쪽만 고치면 다음 사람이
      // 어느 쪽이 맞는지 알 수 없다.
      const firstAvailableStyle = nextModel.styles.find((style) => style.available);
      if (firstAvailableStyle != null) setValue("style", firstAvailableStyle.id);
    }
  };

  return (
    <form
      className="flex flex-col gap-6"
      noValidate
      // `handleSubmit`은 프라미스를 반환하는데 이 속성은 void를 기대한다(no-misused-promises).
      onSubmit={(event) => void handleSubmit(onSubmit)(event)}
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
                  <SelectItem key={model.id} value={model.id} disabled={!model.available}>
                    {model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        />
        {hasUnavailableModel && (
          <p className="text-xs text-muted-foreground">지금 이용 가능한 모델만 선택할 수 있어요</p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="generate-images-style">스타일</Label>
          <Controller
            control={control}
            name="style"
            render={({ field }) => (
              <Select
                value={field.value}
                onValueChange={field.onChange}
                disabled={styleOptions.length === 0}
              >
                <SelectTrigger id="generate-images-style" className="w-full">
                  <SelectValue placeholder="스타일 불러오는 중…" />
                </SelectTrigger>
                <SelectContent>
                  {styleOptions.map((style) => (
                    // BE가 스타일 4종을 내리기 시작하는 시점과 PR ②의 스타일 그리드가 이 Select를
                    // 대체하는 시점 사이 구간에 대한 최소 안전망이다(image-refact-techspec.md §6-2) —
                    // 없으면 미가용 스타일을 골라 생성 시 400을 받는다. PR ②에서 그리드로 대체되며
                    // 이 자리는 사라진다.
                    <SelectItem key={style.id} value={style.id} disabled={!style.available}>
                      {style.name}
                      {!style.available && " · 준비 중"}
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

      <div>
        {/* 모델 목록이 아직 로딩 중이면 model/style이 비어 있어 제출해도 zod가 조용히 막는다(그 필드엔
            에러 텍스트 UI가 없다) — 누를 게 없는 상태를 숨기지 않고 버튼을 함께 잠근다. */}
        <Button type="submit" disabled={isSubmitting || isModelsPending}>
          이미지 생성
        </Button>
      </div>
    </form>
  );
}
