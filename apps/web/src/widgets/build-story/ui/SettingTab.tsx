import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Controller, useWatch, type UseFormReturn } from "react-hook-form";

import type { StoryBuilderFormValues } from "../../../features/build-story";

const PROMPT_TEMPLATE_OPTIONS: { value: "basic" | "emotional" | "simulation" | "custom"; label: string }[] = [
  { value: "basic", label: "기본" },
  { value: "emotional", label: "감정형" },
  { value: "simulation", label: "시뮬레이션형" },
  { value: "custom", label: "커스텀" },
];

/** techspec-builder-story.md §1 — 프롬프트 템플릿(필수, 기본값 "기본") 선택에 따라 세계관/전개예시
 * 또는 커스텀 프롬프트 입력 폼을 전환한다. 숨겨진 필드는 RHF 기본 동작(shouldUnregister: false)대로
 * 언마운트돼도 값이 폼 상태에 그대로 보존된다. */
export function SettingTab({ form }: { form: UseFormReturn<StoryBuilderFormValues> }) {
  const { register, control } = form;
  const promptTemplate = useWatch({ control, name: "storySetting.promptTemplate" });
  const isCustom = promptTemplate === "custom";

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1.5">
        <span className="text-sm leading-none font-medium">프롬프트 템플릿 *</span>
        <Controller
          control={control}
          name="storySetting.promptTemplate"
          render={({ field }) => (
            <ToggleGroup
              type="single"
              variant="outline"
              value={field.value}
              onValueChange={(value) => value && field.onChange(value)}
              aria-label="프롬프트 템플릿"
            >
              {PROMPT_TEMPLATE_OPTIONS.map((option) => (
                <ToggleGroupItem key={option.value} value={option.value} aria-label={option.label}>
                  {option.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        />
      </div>

      {isCustom ? (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="story-setting-custom-prompt">커스텀 프롬프트 *</Label>
          <Textarea
            id="story-setting-custom-prompt"
            placeholder="AI에게 지시할 프롬프트를 자유롭게 작성해주세요"
            rows={12}
            {...register("storySetting.customPrompt")}
          />
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="story-setting-world">스토리 설정/정보 *</Label>
            <Textarea
              id="story-setting-world"
              placeholder="스토리의 세계관과 설정을 입력해주세요"
              rows={8}
              {...register("storySetting.worldSetting")}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="story-setting-development">전개예시 (고급설정)</Label>
            <Textarea
              id="story-setting-development"
              placeholder="이야기가 어떻게 전개될지 예시를 입력해주세요"
              rows={6}
              {...register("storySetting.developmentExample")}
            />
          </div>
        </>
      )}
    </div>
  );
}
