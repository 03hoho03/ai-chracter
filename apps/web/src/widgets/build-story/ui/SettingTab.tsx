import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useRef } from "react";
import { Controller, useFieldArray, useFormContext, useWatch } from "react-hook-form";

import { MAX_DEVELOPMENT_EXAMPLES } from "@/entities/content";
import {
  CollapsibleItemCard,
  focusNeighborToggle,
  indexOpenKey,
  ItemRemoveButton,
  useBuilderUiState,
} from "@/features/build-common";
import {
  FieldLabelText,
  PROMPT_TEMPLATE_LABELS,
  PROMPT_TEMPLATE_VALUES,
  STORY_FIELD_LABELS,
  type StoryBuilderFormValues,
  type StoryCollapsibleList,
} from "@/features/build-story";
import { firstLine } from "@/shared/lib/text/firstLine";

import { MediaTagOutsideNotice } from "./MediaTagOutsideNotice";
import { StoryMacroNotice } from "./StoryMacroNotice";

// 전개 예시는 폼 값에 id 가 없어 열림 키를 배열 위치로 만든다. 지울 때 저장소가 뒤 항목의 열림을 한 칸 당긴다.
const DEVELOPMENT_EXAMPLE_LIST: StoryCollapsibleList = "developmentExample";

/** 프롬프트 템플릿(필수, 기본값 "기본") 선택에 따라 세계관 또는
 * 커스텀 프롬프트 입력 폼을 전환한다. 숨겨진 필드는 RHF 기본 동작(shouldUnregister: false)대로
 * 언마운트돼도 값이 폼 상태에 그대로 보존된다.
 *
 * 규칙·사용자의 역할과 목표·전개 예시(고급설정)는 프롬프트
 * L1 작품 층에서 템플릿과 무관하게 항상 적용되므로 이 템플릿 전환 대상이 아니다
 * (셋 다 발행 필수도 아니다). */
export function SettingTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    register,
    control,
    formState: { errors },
  } = form;
  const promptTemplate = useWatch({ control, name: "storySetting.promptTemplate" });
  const isCustom = promptTemplate === "custom";

  const { fields, append, remove } = useFieldArray({ control, name: "storySetting.developmentExamples" });
  // 머리 줄 요약은 사용자 메시지만 쓴다 — 배열 전체를 구독하면 긴 스토리 응답에 한 글자 칠 때마다 탭 전체가 다시 그려진다.
  const exampleUserLines = useWatch({
    control,
    name: fields.map((_, index) => `storySetting.developmentExamples.${index}.userLine` as const),
  });
  const uiState = useBuilderUiState();
  const addButtonRef = useRef<HTMLButtonElement>(null);

  function handleAppendExample() {
    // 새 항목을 열림으로 기록하는 일은 append 와 같은 핸들러에서 그보다 먼저 한다. 같은 커밋에 본문이 보여야 append 가
    // 주는 포커스가 숨은 입력칸에 걸려 헛돌지 않는다.
    uiState.open([indexOpenKey(DEVELOPMENT_EXAMPLE_LIST, fields.length)]);
    append(
      { userLine: "", assistantLine: "" },
      { focusName: `storySetting.developmentExamples.${fields.length}.userLine` },
    );
  }

  function handleRemoveExample(index: number) {
    // 지우기 전에 포커스를 옮긴다 — 지운 뒤로 미루면 누른 삭제 버튼이 사라지며 포커스가 문서 맨 앞으로 떨어진다. 다음
    // 항목의 토글은 지운 뒤에도 같은 요소로 남고(React key 가 필드 배열 id 다) 열림 키만 한 칸 당겨진다.
    const keys = fields.map((_, itemIndex) => indexOpenKey(DEVELOPMENT_EXAMPLE_LIST, itemIndex));
    focusNeighborToggle(keys, index, addButtonRef.current);
    remove(index);
    uiState.removeIndexKey(DEVELOPMENT_EXAMPLE_LIST, index);
  }

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1.5">
        <span className="text-sm leading-none font-medium"><FieldLabelText field="storySetting.promptTemplate" /></span>
        <Controller
          control={control}
          name="storySetting.promptTemplate"
          render={({ field }) => (
            <>
              <ToggleGroup
                type="single"
                variant="outline"
                ref={field.ref}
                value={field.value}
                onValueChange={(value) => value && field.onChange(value)}
                aria-label="프롬프트 템플릿"
                aria-invalid={!!errors.storySetting?.promptTemplate}
                aria-describedby={
                  errors.storySetting?.promptTemplate ? "story-setting-prompt-template-error" : undefined
                }
              >
                {PROMPT_TEMPLATE_VALUES.map((value) => (
                  <ToggleGroupItem
                    key={value}
                    value={value}
                    aria-label={PROMPT_TEMPLATE_LABELS[value].label}
                    className={cn(
                      errors.storySetting?.promptTemplate && "border-destructive ring-3 ring-destructive/20",
                    )}
                  >
                    {PROMPT_TEMPLATE_LABELS[value].label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              {errors.storySetting?.promptTemplate && (
                <p id="story-setting-prompt-template-error" role="alert" className="text-xs text-destructive-text">
                  {errors.storySetting.promptTemplate.message}
                </p>
              )}
            </>
          )}
        />
        <p className="text-sm text-muted-foreground">{PROMPT_TEMPLATE_LABELS[promptTemplate].description}</p>
      </div>

      {isCustom ? (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="story-setting-custom-prompt"><FieldLabelText field="storySetting.customPrompt" /></Label>
          <Textarea
            id="story-setting-custom-prompt"
            placeholder="AI에게 지시할 프롬프트를 자유롭게 작성해주세요"
            rows={12}
            className="min-h-64"
            aria-invalid={!!errors.storySetting?.customPrompt}
            aria-describedby={errors.storySetting?.customPrompt ? "story-setting-custom-prompt-error" : undefined}
            {...register("storySetting.customPrompt")}
          />
          <MediaTagOutsideNotice name="storySetting.customPrompt" />
          <StoryMacroNotice name="storySetting.customPrompt" />
          {errors.storySetting?.customPrompt && (
            <p id="story-setting-custom-prompt-error" role="alert" className="text-xs text-destructive-text">
              {errors.storySetting.customPrompt.message}
            </p>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="story-setting-world"><FieldLabelText field="storySetting.worldSetting" /></Label>
          <Textarea
            id="story-setting-world"
            placeholder="스토리의 세계관과 설정을 입력해주세요"
            rows={8}
            className="min-h-32"
            aria-invalid={!!errors.storySetting?.worldSetting}
            aria-describedby={errors.storySetting?.worldSetting ? "story-setting-world-error" : undefined}
            {...register("storySetting.worldSetting")}
          />
          <MediaTagOutsideNotice name="storySetting.worldSetting" />
          <StoryMacroNotice name="storySetting.worldSetting" />
          {errors.storySetting?.worldSetting && (
            <p id="story-setting-world-error" role="alert" className="text-xs text-destructive-text">
              {errors.storySetting.worldSetting.message}
            </p>
          )}
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-setting-rules"><FieldLabelText field="storySetting.rules" /></Label>
        <Textarea
          id="story-setting-rules"
          placeholder="진행 중 지켜야 할 규칙을 입력해주세요"
          rows={4}
          aria-invalid={!!errors.storySetting?.rules}
          aria-describedby={errors.storySetting?.rules ? "story-setting-rules-error" : undefined}
          {...register("storySetting.rules")}
        />
        <MediaTagOutsideNotice name="storySetting.rules" />
        <StoryMacroNotice name="storySetting.rules" />
        {errors.storySetting?.rules && (
          <p id="story-setting-rules-error" role="alert" className="text-xs text-destructive-text">
            {errors.storySetting.rules.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-setting-user-goal"><FieldLabelText field="storySetting.userGoal" /></Label>
        <Textarea
          id="story-setting-user-goal"
          placeholder="사용자가 이 이야기에서 맡는 역할과 이루고자 하는 목표를 입력해주세요"
          rows={4}
          aria-invalid={!!errors.storySetting?.userGoal}
          aria-describedby={errors.storySetting?.userGoal ? "story-setting-user-goal-error" : undefined}
          {...register("storySetting.userGoal")}
        />
        <MediaTagOutsideNotice name="storySetting.userGoal" />
        <StoryMacroNotice name="storySetting.userGoal" />
        {errors.storySetting?.userGoal && (
          <p id="story-setting-user-goal-error" role="alert" className="text-xs text-destructive-text">
            {errors.storySetting.userGoal.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-4" data-field-path="storySetting.developmentExamples">
        <Label><FieldLabelText field="storySetting.developmentExamples" /></Label>
        {!!errors.storySetting?.developmentExamples?.message && (
          <p id="story-setting-development-examples-error" role="alert" className="text-xs text-destructive-text">
            {errors.storySetting.developmentExamples.message}
          </p>
        )}
        {fields.map((field, index) => {
          const exampleErrors = errors.storySetting?.developmentExamples?.[index];
          const userLineErrorId = `story-setting-example-${field.id}-user-line-error`;
          const assistantLineErrorId = `story-setting-example-${field.id}-assistant-line-error`;
          const title = `전개 예시 ${index + 1}`;
          return (
            <CollapsibleItemCard
              key={field.id}
              openKey={indexOpenKey(DEVELOPMENT_EXAMPLE_LIST, index)}
              title=""
              placeholderTitle={title}
              summary={firstLine(exampleUserLines[index] ?? "")}
              hasError={!!exampleErrors}
              trailing={<ItemRemoveButton label={`${title} 삭제`} onClick={() => handleRemoveExample(index)} />}
            >
              <div className="flex flex-col gap-2">
                <Textarea
                  placeholder={STORY_FIELD_LABELS["storySetting.developmentExamples.*.userLine"].label}
                  rows={2}
                  aria-invalid={!!exampleErrors?.userLine}
                  aria-describedby={exampleErrors?.userLine ? userLineErrorId : undefined}
                  {...register(`storySetting.developmentExamples.${index}.userLine`)}
                />
                <MediaTagOutsideNotice name={`storySetting.developmentExamples.${index}.userLine`} />
                <StoryMacroNotice name={`storySetting.developmentExamples.${index}.userLine`} />
                {exampleErrors?.userLine && (
                  <p id={userLineErrorId} role="alert" className="text-xs text-destructive-text">
                    {exampleErrors.userLine.message}
                  </p>
                )}
                <Textarea
                  placeholder={STORY_FIELD_LABELS["storySetting.developmentExamples.*.assistantLine"].label}
                  rows={6}
                  aria-invalid={!!exampleErrors?.assistantLine}
                  aria-describedby={exampleErrors?.assistantLine ? assistantLineErrorId : undefined}
                  {...register(`storySetting.developmentExamples.${index}.assistantLine`)}
                />
                <MediaTagOutsideNotice name={`storySetting.developmentExamples.${index}.assistantLine`} />
                <StoryMacroNotice name={`storySetting.developmentExamples.${index}.assistantLine`} />
                {exampleErrors?.assistantLine && (
                  <p id={assistantLineErrorId} role="alert" className="text-xs text-destructive-text">
                    {exampleErrors.assistantLine.message}
                  </p>
                )}
              </div>
            </CollapsibleItemCard>
          );
        })}
        {fields.length < MAX_DEVELOPMENT_EXAMPLES ? (
          <Button ref={addButtonRef} type="button" variant="secondary" onClick={handleAppendExample}>
            전개 예시 추가
          </Button>
        ) : null}
      </div>
    </div>
  );
}
