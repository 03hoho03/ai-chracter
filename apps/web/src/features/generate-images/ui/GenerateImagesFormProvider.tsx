import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { FormProvider, useForm, useWatch } from "react-hook-form";

import { useImageModelsQuery } from "@/entities/image-model";

import { getImageModelsUnavailableReason } from "../model/imageModelsUnavailableReason";
import { isReferenceImageEnabled } from "../model/isReferenceImageEnabled";
import {
  generateImagesDefaultValues,
  generateImagesSchema,
  type GenerateImagesFormValues,
} from "../model/schema";
import {
  GenerateImagesSubmitContext,
  type GenerateImagesSubmitContextValue,
  type GenerateImagesSubmitHelpers,
  type PickedReferenceImage,
} from "../model/useGenerateImagesSubmit";

type GenerateImagesFormProviderProps = {
  onSubmit: (values: GenerateImagesFormValues, helpers: GenerateImagesSubmitHelpers) => void | Promise<void>;
  onPickReference: GenerateImagesSubmitContextValue["onPickReference"];
  children: ReactNode;
};

// 옛 GenerateImagesForm이 갖고 있던 useForm 초기화·모델
// 목록 조회·기본값 자동 적용·불가용 상태 분기를 그대로 옮겼다. 나머지 필드 UI(프롬프트·스타일
// 그리드·모델/비율/개수)는 이 프로바이더 아래 세 조각으로 쪼개졌다.
export function GenerateImagesFormProvider({ onSubmit, onPickReference, children }: GenerateImagesFormProviderProps) {
  const {
    data: models,
    isPending: isModelsPending,
    errorUpdatedAt: modelsErrorUpdatedAt,
    dataUpdatedAt: modelsDataUpdatedAt,
    refetch: refetchModels,
  } = useImageModelsQuery();

  const form = useForm<GenerateImagesFormValues>({
    resolver: zodResolver(generateImagesSchema),
    defaultValues: generateImagesDefaultValues,
  });
  const { getValues, reset, setValue, setError, clearErrors, control } = form;
  const selectedModelId = useWatch({ control, name: "model" });
  const isReferenceEnabled = isReferenceImageEnabled(models, selectedModelId);

  // model/style 기본값은 스키마에 없다 — 목록이 처음 로드되면 첫 가용 모델/스타일로 한 번만
  // reset()한다. 이후 배경 refetch에서는(가용성이 바뀌어도) 다시 손대지 않는다 — 사용자가 이미 고른
  // 값을 조용히 되돌리면 그게 더 놀랍다(`reset()` 선례가 이 저장소에 없어 새로 만든 흐름).
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

  const unavailableReason = getImageModelsUnavailableReason({
    models,
    errorUpdatedAt: modelsErrorUpdatedAt,
    dataUpdatedAt: modelsDataUpdatedAt,
  });
  // 빈 목록은 정적 레지스트리가 빈 것이라 다시 물어도 고쳐지지 않는다.
  const onRetry =
    unavailableReason === "error" || unavailableReason === "unavailable" ? () => void refetchModels() : undefined;

  // 피커가 준 presigned URL은 만료되는 표시 전용 값이라 폼 값이 아니라 state로 둔다. 어느 이미지의
  // 미리보기인지 id를 함께 들고 있다가 필드가 폼 값과 같을 때만 보이므로, 서버 오류로 참조가 비워지거나
  // 다른 이미지로 바뀌면 옛 미리보기가 저절로 떨어진다.
  const [referencePreview, setReferencePreview] = useState<PickedReferenceImage>();
  const referencePickButtonRef = useRef<HTMLButtonElement>(null);

  function setReference(picked: PickedReferenceImage) {
    setReferencePreview(picked);
    setValue("reference", { assetId: picked.assetId }, { shouldDirty: true });
    // `setValue`는 기본으로 재검증하지 않아, 그대로 두면 서버가 건 "참조를 찾지 못함" 오류가 새 참조를
    // 넣은 뒤에도 남는다. 고른 참조는 스키마상 언제나 유효하므로 검증 대신 오류를 바로 지운다.
    clearErrors("reference");
  }

  function focusReferenceField() {
    referencePickButtonRef.current?.focus();
  }

  // 참조 판정은 화면에 보이는 값이 아니라 **제출한 값**의 모델로 다시 한다 — 렌더와 제출 사이에
  // 모델이 바뀌어도 보낸 요청과 판정이 어긋나지 않는다.
  function handleSubmit(values: GenerateImagesFormValues) {
    return onSubmit(values, {
      isReferenceEnabled: isReferenceImageEnabled(models, values.model),
      clearReference: (errorMessage) => {
        setValue("reference", null);
        if (errorMessage !== undefined) setError("reference", { type: "server", message: errorMessage });
      },
    });
  }

  return (
    <FormProvider {...form}>
      <GenerateImagesSubmitContext.Provider
        value={{
          onSubmit: handleSubmit,
          isModelsPending,
          unavailableReason,
          onRetry,
          isReferenceEnabled,
          onPickReference,
          referencePreview,
          setReference,
          referencePickButtonRef,
          focusReferenceField,
        }}
      >
        {children}
      </GenerateImagesSubmitContext.Provider>
    </FormProvider>
  );
}
