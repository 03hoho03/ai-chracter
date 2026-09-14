import { Label } from "@ai-character-chat/ui/components/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ai-character-chat/ui/components/select";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Controller, useFormContext, useWatch } from "react-hook-form";

import { useImageModelsQuery } from "@/entities/image-model";

import {
  IMAGE_ASPECT_RATIO_LABEL,
  IMAGE_ASPECT_RATIOS,
  IMAGE_COUNT_OPTIONS,
  isImageAspectRatio,
  type GenerateImagesFormValues,
} from "../model/schema";

// image-refact-techspec.md IT-13 — 비율·개수는 Select가 아니라 ToggleGroup(칩)이다. 모델 Select는
// 그대로 두되(IR-7, 값이 v1 하나뿐이라 칩으로 바꿀 근거가 없다) 칩 줄과 같은 줄에 두지 않는다 —
// apps/web/CLAUDE.md:124가 "칩 줄 안의 Select는 활성 표현이 뒤집힌다"고 경고한다.
export function GenerateImagesOptionsFields() {
  const { control, setValue, getValues } = useFormContext<GenerateImagesFormValues>();
  const { data: models, isPending: isModelsPending } = useImageModelsQuery();
  const selectedModelId = useWatch({ control, name: "model" });
  const selectedModel = models?.find((model) => model.id === selectedModelId);
  const supportedRatios = new Set<string>(
    selectedModel?.supportedAspectRatios ?? IMAGE_ASPECT_RATIOS,
  );
  const isRatioRestricted =
    selectedModel != null && selectedModel.supportedAspectRatios.length < IMAGE_ASPECT_RATIOS.length;
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
    <div className="flex flex-col gap-4">
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

      <div className="flex flex-col gap-1.5">
        <Label>비율</Label>
        <Controller
          control={control}
          name="aspectRatio"
          render={({ field }) => (
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={field.value}
              onValueChange={(value) => {
                // radix 단일 토글은 선택된 항목을 다시 누르면 ""를 흘려보낸다(ContentTypeToggle.tsx:13-18).
                if (!isImageAspectRatio(value)) return;
                field.onChange(value);
              }}
              aria-label="비율"
              className="grid grid-cols-3"
            >
              {IMAGE_ASPECT_RATIOS.map((ratio) => (
                <ToggleGroupItem
                  key={ratio}
                  value={ratio}
                  disabled={!supportedRatios.has(ratio)}
                  aria-label={IMAGE_ASPECT_RATIO_LABEL[ratio]}
                  // DESIGN.md:262 variant="list" 레시피 — 화면당 primary 솔리드 채움은 CTA 하나뿐이어야
                  // 하는데 이 칩과 아래 개수 칩까지 솔리드면 셋이 된다. 틴트로 내려 예산을 CTA에 남긴다.
                  className="data-[state=on]:border-primary data-[state=on]:bg-primary/10 data-[state=on]:text-primary data-[state=on]:hover:bg-primary/15"
                >
                  {ratio}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        />
        {isRatioRestricted && (
          <p className="text-xs text-muted-foreground">이 모델이 지원하는 비율만 선택할 수 있어요</p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>개수</Label>
        <Controller
          control={control}
          name="count"
          render={({ field }) => (
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={String(field.value)}
              onValueChange={(value) => {
                // radix 단일 토글은 선택된 항목을 다시 누르면 ""를 흘려보낸다(ContentTypeToggle.tsx:13-18).
                if (value === "") return;
                field.onChange(Number(value));
              }}
              aria-label="개수"
            >
              {IMAGE_COUNT_OPTIONS.map((count) => (
                <ToggleGroupItem
                  key={count}
                  value={String(count)}
                  // DESIGN.md:262 variant="list" 레시피 — 위 비율 칩과 같은 이유.
                  className="data-[state=on]:border-primary data-[state=on]:bg-primary/10 data-[state=on]:text-primary data-[state=on]:hover:bg-primary/15"
                >
                  {count}장
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        />
      </div>
    </div>
  );
}
