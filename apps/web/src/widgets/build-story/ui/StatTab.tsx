import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { Controller, useFieldArray, useWatch, type UseFormReturn } from "react-hook-form";

import type { StoryBuilderFormValues } from "../../../features/build-story";
import { ColorPicker, IconPicker } from "../../../shared/ui/color-icon-picker";

/** 스탯 하나(이름/아이콘/색상/최소·최대·초기값/단위/설명). 순서 우선순위가 없어 dnd-kit 없이
 * add/remove만 지원한다(IntroTab의 예시 대화와 동일한 판단, US-101). */
function StatRow({
  id,
  startingSetupIndex,
  statIndex,
  form,
  onRemove,
}: {
  id: string;
  startingSetupIndex: number;
  statIndex: number;
  form: UseFormReturn<StoryBuilderFormValues>;
  onRemove: () => void;
}) {
  const { register, control } = form;

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-background p-4">
      <div className="flex items-start gap-3">
        <Controller
          control={control}
          name={`startingSetups.${startingSetupIndex}.stats.${statIndex}.icon`}
          render={({ field }) => <IconPicker value={field.value} onChange={field.onChange} triggerLabel="아이콘 선택 *" />}
        />
        <Controller
          control={control}
          name={`startingSetups.${startingSetupIndex}.stats.${statIndex}.color`}
          render={({ field }) => <ColorPicker value={field.value} onChange={field.onChange} triggerLabel="색상 선택 *" />}
        />
        <div className="flex flex-1 flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-name`}>이름 *</Label>
          <Input
            id={`stat-${id}-name`}
            placeholder="스탯 이름을 입력해주세요"
            {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.name`)}
          />
        </div>
        <Button type="button" variant="ghost" size="icon" aria-label="스탯 삭제" onClick={onRemove}>
          <Trash2 aria-hidden />
        </Button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-min`}>최소값 *</Label>
          <Input
            id={`stat-${id}-min`}
            type="number"
            {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.min`, { valueAsNumber: true })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-max`}>최대값 *</Label>
          <Input
            id={`stat-${id}-max`}
            type="number"
            {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.max`, { valueAsNumber: true })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-initial`}>초기값 *</Label>
          <Input
            id={`stat-${id}-initial`}
            type="number"
            {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.initial`, {
              valueAsNumber: true,
            })}
          />
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`stat-${id}-unit`}>단위</Label>
        <Input
          id={`stat-${id}-unit`}
          placeholder="예: pt, %"
          {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.unit`)}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`stat-${id}-description`}>설명 *</Label>
        <Textarea
          id={`stat-${id}-description`}
          placeholder="스탯에 대한 설명을 입력해주세요"
          rows={2}
          {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.description`)}
        />
      </div>
    </div>
  );
}

/** 선택된 시작설정 하나의 스탯 목록. `key={시작설정 id}`로 감싸 시작설정을 전환할 때마다
 * useFieldArray가 새 index로 완전히 새로 마운트되게 한다(name의 인덱스만 바뀌는 걸 이 훅이
 * 안정적으로 재구독하지 않아서, 상위 StatTab이 이 컴포넌트 자체를 remount하는 방식으로 우회). */
function StatSection({
  form,
  startingSetupIndex,
}: {
  form: UseFormReturn<StoryBuilderFormValues>;
  startingSetupIndex: number;
}) {
  const { control } = form;
  const { fields, append, remove } = useFieldArray({
    control,
    name: `startingSetups.${startingSetupIndex}.stats`,
  });

  return (
    <div className="flex flex-col gap-4">
      {fields.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-10 text-center">
          <p className="text-sm text-muted-foreground">아직 등록된 스탯이 없어요.</p>
        </div>
      ) : (
        fields.map((field, statIndex) => (
          <StatRow
            key={field.id}
            id={field.id}
            form={form}
            startingSetupIndex={startingSetupIndex}
            statIndex={statIndex}
            onRemove={() => remove(statIndex)}
          />
        ))
      )}

      <Button
        type="button"
        variant="secondary"
        className="w-fit"
        onClick={() =>
          append({
            id: crypto.randomUUID(),
            name: "",
            icon: "",
            color: "",
            min: 0,
            max: 100,
            initial: 0,
            unit: "",
            description: "",
          })
        }
      >
        스탯 추가
      </Button>
    </div>
  );
}

/** techspec-builder-story.md §1.2 AC — 탭 전체가 선택사항(0개도 발행 가능), 스탯은 시작설정별로
 * 독립이라 이 탭은 먼저 시작설정을 고른 뒤 그 시작설정의 스탯만 편집한다. */
export function StatTab({ form }: { form: UseFormReturn<StoryBuilderFormValues> }) {
  const { control } = form;
  const startingSetups = useWatch({ control, name: "startingSetups" });
  const [selectedSetupId, setSelectedSetupId] = useState<string | null>(startingSetups[0]?.id ?? null);

  if (startingSetups.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-20 text-center">
        <p className="text-sm text-muted-foreground">먼저 시작설정 탭에서 시작설정을 추가해주세요.</p>
      </div>
    );
  }

  const selectedIndex = startingSetups.findIndex((setup) => setup.id === selectedSetupId);
  const effectiveIndex = selectedIndex !== -1 ? selectedIndex : 0;
  const effectiveSetup = startingSetups[effectiveIndex];

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1.5">
        <span className="text-sm leading-none font-medium">시작설정 선택 (선택)</span>
        <p className="text-sm text-muted-foreground">
          스탯은 시작설정마다 독립적으로 구성돼요. 스탯을 0개 등록해도 발행할 수 있어요.
        </p>
        <ToggleGroup
          type="single"
          variant="outline"
          className="flex-wrap"
          value={effectiveSetup?.id ?? ""}
          onValueChange={(value) => value && setSelectedSetupId(value)}
          aria-label="시작설정 선택"
        >
          {startingSetups.map((setup, index) => (
            <ToggleGroupItem key={setup.id} value={setup.id} aria-label={setup.name || `시작설정 ${index + 1}`}>
              {setup.name || `시작설정 ${index + 1}`}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      {effectiveSetup && <StatSection key={effectiveSetup.id} form={form} startingSetupIndex={effectiveIndex} />}
    </div>
  );
}
