import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Trash2 } from "lucide-react";
import { Controller, useFieldArray, useFormContext, useWatch } from "react-hook-form";

import type { StoryBuilderFormValues } from "@/features/build-story";

// chat-techspec.md §6-5 — 4단계에서 템플릿마다 실제로 다른 지시문(chat-goal-prompt.md §6)을 갖게
// 되므로, 여기 설명이 빈말이 아니다. 안내문이라 지시문을 그대로 옮기지 않고 창작자가 읽을 말로 풀었다.
const PROMPT_TEMPLATE_OPTIONS: {
  value: "basic" | "emotional" | "simulation" | "custom";
  label: string;
  description: string;
}[] = [
  {
    value: "basic",
    label: "기본",
    description: "상황을 담백하게 그리며, 매 턴 다음 장면으로 이어질 실마리를 남겨요.",
  },
  {
    value: "emotional",
    label: "감정형",
    description: "인물의 감정 변화를 섬세한 단서로 드러내 사용자가 알아챌 수 있게 해요.",
  },
  {
    value: "simulation",
    label: "시뮬레이션형",
    description: "매 턴 무엇이 달라졌는지, 지금 무엇을 조작할 수 있는지 명확히 보여줘요.",
  },
  {
    value: "custom",
    label: "커스텀",
    description: "직접 작성한 프롬프트로 진행하되, 기본 템플릿과 같은 진행 방식이 바탕에 깔려요.",
  },
];

const MAX_DEVELOPMENT_EXAMPLES = 3;

/** techspec-builder-story.md §1 — 프롬프트 템플릿(필수, 기본값 "기본") 선택에 따라 세계관 또는
 * 커스텀 프롬프트 입력 폼을 전환한다. 숨겨진 필드는 RHF 기본 동작(shouldUnregister: false)대로
 * 언마운트돼도 값이 폼 상태에 그대로 보존된다.
 *
 * 규칙·사용자의 역할과 목표·전개 예시(고급설정)는 chat-techspec.md §6-3(D-16)에 따라 프롬프트
 * L1 작품 층에서 템플릿과 무관하게 항상 적용되므로 이 템플릿 전환 대상이 아니다(chat-goal-prompt.md
 * §8, D-19 — 셋 다 발행 필수도 아니다). */
export function SettingTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const { register, control } = form;
  const promptTemplate = useWatch({ control, name: "storySetting.promptTemplate" });
  const isCustom = promptTemplate === "custom";
  const selectedTemplate = PROMPT_TEMPLATE_OPTIONS.find((option) => option.value === promptTemplate);

  const { fields, append, remove } = useFieldArray({ control, name: "storySetting.developmentExamples" });

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
        {selectedTemplate ? <p className="text-sm text-muted-foreground">{selectedTemplate.description}</p> : null}
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
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="story-setting-world">스토리 설정/정보 *</Label>
          <Textarea
            id="story-setting-world"
            placeholder="스토리의 세계관과 설정을 입력해주세요"
            rows={8}
            {...register("storySetting.worldSetting")}
          />
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-setting-rules">규칙</Label>
        <Textarea
          id="story-setting-rules"
          placeholder="진행 중 지켜야 할 규칙을 입력해주세요"
          rows={4}
          {...register("storySetting.rules")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-setting-user-goal">사용자의 역할과 목표</Label>
        <Textarea
          id="story-setting-user-goal"
          placeholder="사용자가 이 이야기에서 맡는 역할과 이루고자 하는 목표를 입력해주세요"
          rows={4}
          {...register("storySetting.userGoal")}
        />
      </div>

      <div className="flex flex-col gap-4">
        <Label>전개 예시 (고급설정, 최대 {MAX_DEVELOPMENT_EXAMPLES}개)</Label>
        {fields.map((field, index) => (
          <div key={field.id} className="flex flex-col gap-2 rounded-xl border border-border p-4">
            <div className="flex items-start gap-2">
              <div className="flex flex-1 flex-col gap-2">
                <Input
                  placeholder="사용자 메시지"
                  {...register(`storySetting.developmentExamples.${index}.userLine`)}
                />
                <Input
                  placeholder="스토리 응답"
                  {...register(`storySetting.developmentExamples.${index}.assistantLine`)}
                />
              </div>
              <Button type="button" variant="ghost" size="icon" aria-label="전개 예시 삭제" onClick={() => remove(index)}>
                <Trash2 />
              </Button>
            </div>
          </div>
        ))}
        {fields.length < MAX_DEVELOPMENT_EXAMPLES ? (
          <Button type="button" variant="secondary" onClick={() => append({ userLine: "", assistantLine: "" })}>
            전개 예시 추가
          </Button>
        ) : null}
      </div>
    </div>
  );
}
