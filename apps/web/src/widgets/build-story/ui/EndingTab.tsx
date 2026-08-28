import {
  closestCenter,
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { GripVertical, Trash2 } from "lucide-react";
import { useState } from "react";
import { useFieldArray, useWatch, type UseFormReturn } from "react-hook-form";

import type {
  RuleListItemValues,
  SingleRuleValues,
  StatDefValues,
  StoryBuilderFormValues,
} from "@/features/build-story";

const COMPARISON_OPERATORS: SingleRuleValues["operator"][] = [">", ">=", "<", "<=", "=="];

/** 목록 위에서 인접한 두 항목 사이의 and/or 관계. 마지막 항목의 nextOp는 평가에서 무시되므로
 * (shared/lib/rule-engine) 마지막 항목 뒤에는 렌더링하지 않는다. */
function LogicOpToggle({ value, onChange }: { value: "and" | "or"; onChange: (op: "and" | "or") => void }) {
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      className="ml-7 w-fit"
      value={value}
      onValueChange={(next) => next && onChange(next as "and" | "or")}
      aria-label="다음 규칙과의 관계"
    >
      <ToggleGroupItem value="and">그리고</ToggleGroupItem>
      <ToggleGroupItem value="or">또는</ToggleGroupItem>
    </ToggleGroup>
  );
}

/** 단일 규칙 한 줄(스탯/연산자/기준값). 그룹 내부와 최상위 목록 양쪽에서 재사용된다. */
function SingleRuleRow({
  rule,
  stats,
  onChange,
  onRemove,
}: {
  rule: SingleRuleValues;
  stats: StatDefValues[];
  onChange: (rule: SingleRuleValues) => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: rule.id });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="flex items-center gap-2 rounded-lg border border-border bg-background p-3"
    >
      <button
        type="button"
        aria-label="순서 변경"
        className="cursor-grab touch-none text-muted-foreground hover:text-foreground focus-visible:outline-none"
        {...attributes}
        {...listeners}
      >
        <GripVertical aria-hidden className="size-4" />
      </button>

      <Select value={rule.statId} onValueChange={(value) => onChange({ ...rule, statId: value })}>
        <SelectTrigger className="w-32" aria-label="스탯 선택">
          <SelectValue placeholder="스탯" />
        </SelectTrigger>
        <SelectContent>
          {stats.map((stat) => (
            <SelectItem key={stat.id} value={stat.id}>
              {stat.name || "이름없음"}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={rule.operator}
        onValueChange={(value) => onChange({ ...rule, operator: value as SingleRuleValues["operator"] })}
      >
        <SelectTrigger className="w-20" aria-label="연산자 선택">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {COMPARISON_OPERATORS.map((op) => (
            <SelectItem key={op} value={op}>
              {op}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Input
        id={`rule-${rule.id}-value`}
        type="number"
        className="w-24"
        aria-label="기준값"
        value={rule.value}
        onChange={(event) => onChange({ ...rule, value: Number(event.target.value) })}
      />

      <Button type="button" variant="ghost" size="icon" aria-label="규칙 삭제" className="ml-auto" onClick={onRemove}>
        <Trash2 aria-hidden className="size-4" />
      </Button>
    </div>
  );
}

/** 규칙 그룹 컨테이너(내부는 단일 규칙만, 중첩 불가) — 내부 목록은 아래 RuleListEditor를 그대로
 * 재사용한다(techspec-builder-story.md §1.5: "그룹 안의 rules 배열도 동일한 재정렬 UI를 재사용"). */
function RuleGroupRow({
  group,
  stats,
  onChange,
  onRemove,
}: {
  group: Extract<RuleListItemValues, { kind: "group" }>;
  stats: StatDefValues[];
  onChange: (group: Extract<RuleListItemValues, { kind: "group" }>) => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: group.id });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="flex flex-col gap-3 rounded-lg border border-dashed border-border p-3"
    >
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          aria-label="순서 변경"
          className="cursor-grab touch-none text-muted-foreground hover:text-foreground focus-visible:outline-none"
          {...attributes}
          {...listeners}
        >
          <GripVertical aria-hidden className="size-4" />
        </button>
        <span className="mr-auto text-sm font-medium text-foreground">규칙 그룹</span>
        <Button type="button" variant="ghost" size="icon" aria-label="규칙 그룹 삭제" onClick={onRemove}>
          <Trash2 aria-hidden className="size-4" />
        </Button>
      </div>

      <RuleListEditor
        items={group.rules}
        stats={stats}
        allowGroups={false}
        onChange={(next) =>
          onChange({ ...group, rules: next.filter((item): item is SingleRuleValues => item.kind === "rule") })
        }
      />
    </div>
  );
}

/** 스탯 기반 규칙 목록 편집기. "단일 규칙 추가"/"규칙 그룹 추가"로 항목을 늘리고 dnd-kit로 재정렬한다.
 * `allowGroups=false`로 그룹 내부(단일 규칙만)에도 그대로 재사용된다(techspec-builder-story.md §1.5). */
function RuleListEditor({
  items,
  stats,
  allowGroups,
  onChange,
}: {
  items: RuleListItemValues[];
  stats: StatDefValues[];
  allowGroups: boolean;
  onChange: (items: RuleListItemValues[]) => void;
}) {
  const sensors = useSensors(useSensor(PointerSensor));

  function updateItem(id: string, next: RuleListItemValues) {
    onChange(items.map((item) => (item.id === id ? next : item)));
  }

  function removeItem(id: string) {
    onChange(items.filter((item) => item.id !== id));
  }

  function handleDragEnd({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return;
    const oldIndex = items.findIndex((item) => item.id === active.id);
    const newIndex = items.findIndex((item) => item.id === over.id);
    if (oldIndex !== -1 && newIndex !== -1) onChange(arrayMove(items, oldIndex, newIndex));
  }

  return (
    <div className="flex flex-col gap-3">
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          등록된 규칙이 없어요. 비워두면 판단 프롬프트만으로 엔딩을 판정해요.
        </p>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={items.map((item) => item.id)} strategy={verticalListSortingStrategy}>
            <div className="flex flex-col gap-2">
              {items.map((item, index) => (
                <div key={item.id} className="flex flex-col gap-2">
                  {item.kind === "group" ? (
                    <RuleGroupRow
                      group={item}
                      stats={stats}
                      onChange={(next) => updateItem(item.id, next)}
                      onRemove={() => removeItem(item.id)}
                    />
                  ) : (
                    <SingleRuleRow
                      rule={item}
                      stats={stats}
                      onChange={(next) => updateItem(item.id, next)}
                      onRemove={() => removeItem(item.id)}
                    />
                  )}
                  {index < items.length - 1 && (
                    <LogicOpToggle
                      value={item.nextOp ?? "and"}
                      onChange={(op) => updateItem(item.id, { ...item, nextOp: op })}
                    />
                  )}
                </div>
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      <div className="flex gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={stats.length === 0}
          onClick={() =>
            onChange([
              ...items,
              {
                kind: "rule",
                id: crypto.randomUUID(),
                statId: stats[0]?.id ?? "",
                operator: ">=",
                value: 0,
                nextOp: null,
              },
            ])
          }
        >
          단일 규칙 추가
        </Button>
        {allowGroups && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => onChange([...items, { kind: "group", id: crypto.randomUUID(), rules: [], nextOp: null }])}
          >
            규칙 그룹 추가
          </Button>
        )}
      </div>
    </div>
  );
}

/** 엔딩 하나(이름/엔딩조건/판단 프롬프트 필수, 에필로그/엔딩힌트 선택 + 스탯 기반 규칙). */
function EndingRow({
  id,
  form,
  startingSetupIndex,
  endingIndex,
  stats,
  onRemove,
}: {
  id: string;
  form: UseFormReturn<StoryBuilderFormValues>;
  startingSetupIndex: number;
  endingIndex: number;
  stats: StatDefValues[];
  onRemove: () => void;
}) {
  const { register, control, setValue } = form;
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id });
  const statRules = useWatch({
    control,
    name: `startingSetups.${startingSetupIndex}.endings.${endingIndex}.statRules`,
  });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="flex flex-col gap-4 rounded-xl border border-border bg-background p-4"
    >
      <div className="flex items-start gap-3">
        <button
          type="button"
          aria-label="순서 변경"
          className="mt-1.5 cursor-grab touch-none text-muted-foreground hover:text-foreground focus-visible:outline-none"
          {...attributes}
          {...listeners}
        >
          <GripVertical aria-hidden />
        </button>

        <div className="flex flex-1 flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`ending-${id}-name`}>이름 *</Label>
            <Input
              id={`ending-${id}-name`}
              placeholder="엔딩 이름을 입력해주세요"
              {...register(`startingSetups.${startingSetupIndex}.endings.${endingIndex}.name`)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`ending-${id}-turn-gate`}>엔딩조건 (최소 턴수) *</Label>
            <Input
              id={`ending-${id}-turn-gate`}
              type="number"
              min={10}
              {...register(`startingSetups.${startingSetupIndex}.endings.${endingIndex}.turnGate`, {
                valueAsNumber: true,
              })}
            />
            <p className="text-xs text-muted-foreground">최소 10턴 이상 진행돼야 이 엔딩을 판정해요.</p>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`ending-${id}-judge-prompt`}>판단 프롬프트 *</Label>
            <Textarea
              id={`ending-${id}-judge-prompt`}
              placeholder="이 엔딩에 도달했는지 AI가 판단할 기준을 입력해주세요"
              rows={3}
              {...register(`startingSetups.${startingSetupIndex}.endings.${endingIndex}.judgePrompt`)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`ending-${id}-epilogue`}>에필로그</Label>
            <Textarea
              id={`ending-${id}-epilogue`}
              placeholder="엔딩 도달 시 보여줄 에필로그를 입력해주세요"
              rows={3}
              {...register(`startingSetups.${startingSetupIndex}.endings.${endingIndex}.epilogue`)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`ending-${id}-hint`}>엔딩힌트</Label>
            <Input
              id={`ending-${id}-hint`}
              placeholder="엔딩 힌트를 입력해주세요"
              {...register(`startingSetups.${startingSetupIndex}.endings.${endingIndex}.hint`)}
            />
          </div>
        </div>

        <Button type="button" variant="ghost" size="icon" aria-label="엔딩 삭제" onClick={onRemove}>
          <Trash2 aria-hidden />
        </Button>
      </div>

      <div className="flex flex-col gap-2 rounded-xl border border-border px-4 py-3">
        <span className="text-sm leading-none font-medium">스탯 기반 규칙 (선택)</span>
        <RuleListEditor
          items={statRules}
          stats={stats}
          allowGroups
          onChange={(next) =>
            setValue(`startingSetups.${startingSetupIndex}.endings.${endingIndex}.statRules`, next, {
              shouldDirty: true,
            })
          }
        />
      </div>
    </div>
  );
}

/** 선택된 시작설정 하나의 엔딩 목록. `key={시작설정 id}`로 감싸 StatSection과 동일하게 시작설정
 * 전환마다 useFieldArray를 완전히 새로 마운트한다(US-109 패턴). */
function EndingSection({
  form,
  startingSetupIndex,
}: {
  form: UseFormReturn<StoryBuilderFormValues>;
  startingSetupIndex: number;
}) {
  const { control } = form;
  const { fields, append, remove, move } = useFieldArray({
    control,
    name: `startingSetups.${startingSetupIndex}.endings`,
  });
  const stats = useWatch({ control, name: `startingSetups.${startingSetupIndex}.stats` });
  const sensors = useSensors(useSensor(PointerSensor));

  function handleDragEnd({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return;
    const oldIndex = fields.findIndex((field) => field.id === active.id);
    const newIndex = fields.findIndex((field) => field.id === over.id);
    if (oldIndex !== -1 && newIndex !== -1) move(oldIndex, newIndex);
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        같은 턴에 여러 엔딩 조건이 동시에 충족되면 목록 위쪽 엔딩이 우선 발동돼요.
      </p>

      {fields.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-10 text-center">
          <p className="text-sm text-muted-foreground">아직 등록된 엔딩이 없어요.</p>
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={fields.map((field) => field.id)} strategy={verticalListSortingStrategy}>
            <div className="flex flex-col gap-4">
              {fields.map((field, index) => (
                <EndingRow
                  key={field.id}
                  id={field.id}
                  form={form}
                  startingSetupIndex={startingSetupIndex}
                  endingIndex={index}
                  stats={stats}
                  onRemove={() => remove(index)}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      <Button
        type="button"
        variant="secondary"
        className="w-fit"
        onClick={() =>
          append({
            id: crypto.randomUUID(),
            name: "",
            turnGate: 10,
            judgePrompt: "",
            statRules: [],
            epilogue: "",
            hint: "",
          })
        }
      >
        엔딩 추가
      </Button>
    </div>
  );
}

/** techspec-builder-story.md §1.5 AC — 엔딩은 시작설정별 독립 목록이라 StatTab과 동일하게 먼저
 * 시작설정을 고른다(0개 등록해도 발행 가능, 열린 결말). */
export function EndingTab({ form }: { form: UseFormReturn<StoryBuilderFormValues> }) {
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
          엔딩은 시작설정마다 독립적으로 구성돼요. 엔딩을 0개 등록해도 발행할 수 있어요(열린 결말).
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

      {effectiveSetup && <EndingSection key={effectiveSetup.id} form={form} startingSetupIndex={effectiveIndex} />}
    </div>
  );
}
