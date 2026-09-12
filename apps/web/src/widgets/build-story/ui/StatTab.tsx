import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { Controller, useFieldArray, useFormContext, useWatch } from "react-hook-form";

import { STAT_ICON_OPTIONS } from "@/entities/chat-room";
import type { StoryBuilderFormValues } from "@/features/build-story";
import { ColorPicker, IconPicker } from "@/shared/ui/color-icon-picker";

/** techspec-builder-story.md §1.2 AC — 탭 전체가 선택사항(0개도 발행 가능), 스탯은 시작설정별로
 * 독립이라 이 탭은 먼저 시작설정을 고른 뒤 그 시작설정의 스탯만 편집한다. */
export function StatTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const { control } = form;
  const startingSetups = useWatch({ control, name: "startingSetups" });
  const [selectedSetupId, setSelectedSetupId] = useState<string | undefined>(startingSetups[0]?.id);

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

      {effectiveSetup && <StatSection key={effectiveSetup.id} startingSetupIndex={effectiveIndex} />}
    </div>
  );
}

type StatRowProps = {
  id: string;
  startingSetupIndex: number;
  statIndex: number;
  onRemove: () => void;
};

/** 스탯 하나(이름/아이콘/색상/최소·최대·초기값/단위/설명). 순서 우선순위가 없어 dnd-kit 없이
 * add/remove만 지원한다(IntroTab의 예시 대화와 동일한 판단, US-101). */
function StatRow({
  id,
  startingSetupIndex,
  statIndex,
  onRemove,
}: StatRowProps) {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    register,
    control,
    formState: { errors },
  } = form;
  const statErrors = errors.startingSetups?.[startingSetupIndex]?.stats?.[statIndex];

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-background p-4">
      <div className="flex items-start gap-3">
        <Controller
          control={control}
          name={`startingSetups.${startingSetupIndex}.stats.${statIndex}.icon`}
          render={({ field }) => (
            <div
              className="flex flex-col gap-1"
              data-field-path={`startingSetups.${startingSetupIndex}.stats.${statIndex}.icon`}
            >
              <IconPicker
                value={field.value}
                onChange={field.onChange}
                options={STAT_ICON_OPTIONS}
                triggerLabel="아이콘 선택 *"
              />
              {statErrors?.icon && (
                <p id={`stat-${id}-icon-error`} role="alert" className="text-xs text-destructive-text">
                  {statErrors.icon.message}
                </p>
              )}
            </div>
          )}
        />
        <Controller
          control={control}
          name={`startingSetups.${startingSetupIndex}.stats.${statIndex}.color`}
          render={({ field }) => (
            <div
              className="flex flex-col gap-1"
              data-field-path={`startingSetups.${startingSetupIndex}.stats.${statIndex}.color`}
            >
              <ColorPicker value={field.value} onChange={field.onChange} triggerLabel="색상 선택 *" />
              {statErrors?.color && (
                <p id={`stat-${id}-color-error`} role="alert" className="text-xs text-destructive-text">
                  {statErrors.color.message}
                </p>
              )}
            </div>
          )}
        />
        <div className="flex flex-1 flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-name`}>이름 *</Label>
          <Input
            id={`stat-${id}-name`}
            placeholder="스탯 이름을 입력해주세요"
            aria-invalid={!!statErrors?.name}
            aria-describedby={statErrors?.name ? `stat-${id}-name-error` : undefined}
            {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.name`)}
          />
          {statErrors?.name && (
            <p id={`stat-${id}-name-error`} role="alert" className="text-xs text-destructive-text">
              {statErrors.name.message}
            </p>
          )}
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
            aria-invalid={!!statErrors?.min}
            aria-describedby={statErrors?.min ? `stat-${id}-min-error` : undefined}
            {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.min`, { valueAsNumber: true })}
          />
          {statErrors?.min && (
            <p id={`stat-${id}-min-error`} role="alert" className="text-xs text-destructive-text">
              {statErrors.min.message}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-max`}>최대값 *</Label>
          <Input
            id={`stat-${id}-max`}
            type="number"
            aria-invalid={!!statErrors?.max}
            aria-describedby={statErrors?.max ? `stat-${id}-max-error` : undefined}
            {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.max`, { valueAsNumber: true })}
          />
          {statErrors?.max && (
            <p id={`stat-${id}-max-error`} role="alert" className="text-xs text-destructive-text">
              {statErrors.max.message}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-initial`}>초기값 *</Label>
          <Input
            id={`stat-${id}-initial`}
            type="number"
            aria-invalid={!!statErrors?.initial}
            aria-describedby={statErrors?.initial ? `stat-${id}-initial-error` : undefined}
            {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.initial`, {
              valueAsNumber: true,
            })}
          />
          {statErrors?.initial && (
            <p id={`stat-${id}-initial-error`} role="alert" className="text-xs text-destructive-text">
              {statErrors.initial.message}
            </p>
          )}
        </div>
      </div>

      {/* 360px에서 2열이면 한 칸이 134px로 좁아져 아래 힌트가 5줄로 접힌다 — 좁을 땐 1열로 편다
          (앱의 기존 반응형 패턴: grid-cols-1 ... sm:grid-cols-N). */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-unit`}>단위</Label>
          <Input
            id={`stat-${id}-unit`}
            placeholder="예: pt, %"
            aria-invalid={!!statErrors?.unit}
            aria-describedby={statErrors?.unit ? `stat-${id}-unit-error` : undefined}
            {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.unit`)}
          />
          {statErrors?.unit && (
            <p id={`stat-${id}-unit-error`} role="alert" className="text-xs text-destructive-text">
              {statErrors.unit.message}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-per-turn-delta`}>턴당 자동 변화</Label>
          <Input
            id={`stat-${id}-per-turn-delta`}
            type="number"
            step={1}
            placeholder="예: -1"
            aria-invalid={!!statErrors?.perTurnDelta}
            aria-describedby={[
              `stat-${id}-per-turn-delta-hint`,
              statErrors?.perTurnDelta ? `stat-${id}-per-turn-delta-error` : undefined,
            ]
              .filter(Boolean)
              .join(" ")}
            // 빈 칸에 valueAsNumber를 쓰면 NaN이 들어가 zod가 막는다 — 빈 칸은 undefined로 되돌린다.
            {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.perTurnDelta`, {
              setValueAs: (value) => (value === "" || value === null ? undefined : Number(value)),
            })}
          />
          <p id={`stat-${id}-per-turn-delta-hint`} className="text-xs text-muted-foreground">
            매 턴 이만큼 자동으로 변해요(줄어들면 -1처럼 음수). 비워두면 AI가 대화를 보고 판단해요.
          </p>
          {statErrors?.perTurnDelta && (
            <p id={`stat-${id}-per-turn-delta-error`} role="alert" className="text-xs text-destructive-text">
              {statErrors.perTurnDelta.message}
            </p>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`stat-${id}-description`}>설명 *</Label>
        <Textarea
          id={`stat-${id}-description`}
          placeholder="스탯에 대한 설명을 입력해주세요"
          rows={2}
          aria-invalid={!!statErrors?.description}
          aria-describedby={statErrors?.description ? `stat-${id}-description-error` : undefined}
          {...register(`startingSetups.${startingSetupIndex}.stats.${statIndex}.description`)}
        />
        {statErrors?.description && (
          <p id={`stat-${id}-description-error`} role="alert" className="text-xs text-destructive-text">
            {statErrors.description.message}
          </p>
        )}
      </div>
    </div>
  );
}

/** 선택된 시작설정 하나의 스탯 목록. `key={시작설정 id}`로 감싸 시작설정을 전환할 때마다
 * useFieldArray가 새 index로 완전히 새로 마운트되게 한다(name의 인덱스만 바뀌는 걸 이 훅이
 * 안정적으로 재구독하지 않아서, 상위 StatTab이 이 컴포넌트 자체를 remount하는 방식으로 우회). */
function StatSection({ startingSetupIndex }: { startingSetupIndex: number }) {
  const form = useFormContext<StoryBuilderFormValues>();

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
