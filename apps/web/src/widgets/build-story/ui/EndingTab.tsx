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
import { useRef } from "react";
import { useFieldArray, useFormContext, useWatch } from "react-hook-form";

import {
  CollapsibleItemCard,
  focusNeighborToggle,
  ItemDragHandle,
  ItemRemoveButton,
  itemOpenKey,
  useBuilderSelection,
  useBuilderUiState,
} from "@/features/build-common";
import {
  COMPARISON_OPERATORS,
  LOGIC_OPERATORS,
  removeRuleListItem,
  SELECTED_STARTING_SETUP,
  type RuleListItemValues,
  type SingleRuleValues,
  type StatDefValues,
  type StoryBuilderFormValues,
  type StoryCollapsibleList,
} from "@/features/build-story";

import { MediaTagInsertButton } from "./MediaTagInsertButton";
import { MediaTagOutsideNotice } from "./MediaTagOutsideNotice";
import { StartingSetupPicker } from "./StartingSetupPicker";
import { UnknownMediaTagNotice } from "./UnknownMediaTagNotice";

type LogicOp = (typeof LOGIC_OPERATORS)[number];

/** 그룹 내부 규칙을 잇는 접속사. 화면이 이 목록(LOGIC_OPERATORS)으로 항목을 그리므로 술어와 어긋날 수 없다. */
const GROUP_OPERATOR_LABEL: Record<LogicOp, string> = {
  and: "그리고",
  or: "또는",
};

/** 열림 키의 목록 이름 — 발행 실패 때 셸이 오류 항목을 여는 키와 같은 이름이어야 한다(타입이 목록 정의의 키로 묶는다). */
const ENDING_LIST: StoryCollapsibleList = "ending";
const RULE_GROUP_LIST: StoryCollapsibleList = "ruleGroup";

/** 엔딩은 시작설정별 독립 목록이라 StatTab과 동일하게 먼저
 * 시작설정을 고른다(0개 등록해도 발행 가능, 열린 결말). 고른 시작설정은 스탯 탭과 함께 셸의 화면 상태에서 읽고 쓴다. */
export function EndingTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const { control } = form;
  const startingSetups = useWatch({ control, name: "startingSetups" });
  const [selectedSetupId, setSelectedSetupId] = useBuilderSelection(SELECTED_STARTING_SETUP);

  if (startingSetups.length === 0) {
    // 다른 탭 본문과 같은 `py-6` 루트로 감싸야 탭 목록과의 간격이 탭마다 같다.
    return (
      <div className="py-6">
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-20 text-center">
          <p className="text-sm break-keep text-muted-foreground">먼저 시작설정 탭에서 시작설정을 추가해주세요.</p>
        </div>
      </div>
    );
  }

  // 기억해 둔 시작설정이 지워졌거나 아직 고른 적이 없으면 첫 시작설정을 보인다.
  const selectedIndex = startingSetups.findIndex((setup) => setup.id === selectedSetupId);
  const effectiveIndex = selectedIndex !== -1 ? selectedIndex : 0;
  const effectiveSetup = startingSetups[effectiveIndex];

  return (
    <div className="flex flex-col gap-6 py-6">
      <StartingSetupPicker
        startingSetups={startingSetups}
        selectedIndex={effectiveIndex}
        onSelect={setSelectedSetupId}
        itemNoun="엔딩"
        note="엔딩이 하나도 없어도 발행할 수 있어요(열린 결말)."
      />

      {effectiveSetup && <EndingSection key={effectiveSetup.id} startingSetupIndex={effectiveIndex} />}
    </div>
  );
}

/** Radix 토글·셀렉트는 재클릭 시 빈 문자열을 흘려보내고 item value도 `string`이라 좁힘이 필요하다.
 * `as` 대신 술어를 쓴다 — 둘 다 화면이 실제로 그리는 목록을 근거로 삼는다. */
function isGroupOperator(value: string): value is LogicOp {
  return LOGIC_OPERATORS.some((op) => op === value);
}

function isComparisonOperator(value: string): value is SingleRuleValues["operator"] {
  return COMPARISON_OPERATORS.some((op) => op === value);
}

/** 목록 위에서 인접한 두 항목 사이의 and/or 관계. 마지막 항목의 nextOp는 평가에서 무시되므로
 * (entities/chat-room/model/endingRules.ts) 마지막 항목 뒤에는 렌더링하지 않는다. */
function LogicOpToggle({ value, onChange }: { value: LogicOp; onChange: (op: LogicOp) => void }) {
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      className="ml-7 w-fit"
      value={value}
      onValueChange={(next) => isGroupOperator(next) && onChange(next)}
      aria-label="다음 규칙과의 관계"
    >
      {LOGIC_OPERATORS.map((op) => (
        <ToggleGroupItem key={op} value={op}>
          {GROUP_OPERATOR_LABEL[op]}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

type SingleRuleRowProps = {
  rule: SingleRuleValues;
  stats: StatDefValues[];
  onChange: (rule: SingleRuleValues) => void;
  onRemove: () => void;
};

/** 단일 규칙 한 줄(스탯/연산자/기준값). 그룹 내부와 최상위 목록 양쪽에서 재사용된다. */
function SingleRuleRow({
  rule,
  stats,
  onChange,
  onRemove,
}: SingleRuleRowProps) {
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
        className="shrink-0 cursor-grab touch-none rounded-md text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        {...attributes}
        {...listeners}
      >
        <GripVertical aria-hidden className="size-4" />
      </button>

      {/* 세 컨트롤의 고정 폭 합(128+80+96px + 간격)이 좁은 행보다 넓어서, 한 줄에 두면 줄어들 수 있는
          유일한 칸인 기준값 입력이 26px로 찌그러지고 삭제 버튼이 행 밖으로 밀려났다(390px 실측).
          같은 행이 최상위 목록과 규칙 그룹 안 양쪽에 들어가 폭이 뷰포트만으로 정해지지 않으므로
          브레이크포인트 대신 컨테이너 폭으로 가른다 — 좁으면 스탯을 한 줄로 올리고 연산자·기준값을
          다음 줄에 둔다. */}
      <div className="@container min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={rule.statId} onValueChange={(value) => onChange({ ...rule, statId: value })}>
            <SelectTrigger className="w-full @xs:w-32" aria-label="스탯 선택">
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
            onValueChange={(value) => isComparisonOperator(value) && onChange({ ...rule, operator: value })}
          >
            <SelectTrigger className="w-20 shrink-0" aria-label="연산자 선택">
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
            className="w-24 shrink-0"
            aria-label="기준값"
            value={rule.value}
            onChange={(event) => onChange({ ...rule, value: Number(event.target.value) })}
          />
        </div>
      </div>

      <Button type="button" variant="ghost" size="icon" aria-label="규칙 삭제" className="shrink-0" onClick={onRemove}>
        <Trash2 aria-hidden className="size-4" />
      </Button>
    </div>
  );
}

type RuleGroupRowProps = {
  group: Extract<RuleListItemValues, { kind: "group" }>;
  /** 같은 목록 안에서 몇 번째 그룹인지(1부터). 그룹은 이름이 없어 손잡이·삭제 버튼의 이름을 이 순번으로 가른다. */
  groupOrdinal: number;
  stats: StatDefValues[];
  onChange: (group: Extract<RuleListItemValues, { kind: "group" }>) => void;
  onRemove: () => void;
};

/** 규칙 그룹 컨테이너(내부는 단일 규칙만, 중첩 불가) — 내부 목록은 아래 RuleListEditor를 그대로
 * 재사용한다("그룹 안의 rules 배열도 동일한 재정렬 UI를 재사용"). 엔딩 카드 본문 안에서 한 번 더 접히는 카드라, 바깥
 * 엔딩 카드와 구별되게 점선 테두리와 조금 좁은 안쪽 여백을 유지한다. */
function RuleGroupRow({
  group,
  groupOrdinal,
  stats,
  onChange,
  onRemove,
}: RuleGroupRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: group.id });

  return (
    <CollapsibleItemCard
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="rounded-lg border-dashed px-3"
      openKey={itemOpenKey(RULE_GROUP_LIST, group.id)}
      title="규칙 그룹"
      placeholderTitle="규칙 그룹"
      srTitlePrefix={`${groupOrdinal}번째 `}
      summary={`조건 ${group.rules.length}개`}
      leading={<ItemDragHandle {...attributes} {...listeners} aria-label={`${groupOrdinal}번째 규칙 그룹 순서 변경`} />}
      trailing={<ItemRemoveButton label={`${groupOrdinal}번째 규칙 그룹 삭제`} onClick={onRemove} />}
    >
      <RuleListEditor
        items={group.rules}
        stats={stats}
        allowGroups={false}
        onChange={(next) =>
          onChange({ ...group, rules: next.filter((item): item is SingleRuleValues => item.kind === "rule") })
        }
      />
    </CollapsibleItemCard>
  );
}

type RuleListEditorProps = {
  items: RuleListItemValues[];
  stats: StatDefValues[];
  allowGroups: boolean;
  onChange: (items: RuleListItemValues[]) => void;
};

/** 스탯 기반 규칙 목록 편집기. "단일 규칙 추가"/"규칙 그룹 추가"로 항목을 늘리고 dnd-kit로 재정렬한다.
 * `allowGroups=false`로 그룹 내부(단일 규칙만)에도 그대로 재사용된다. */
function RuleListEditor({
  items,
  stats,
  allowGroups,
  onChange,
}: RuleListEditorProps) {
  const sensors = useSensors(useSensor(PointerSensor));
  const uiState = useBuilderUiState();
  const addRuleButtonRef = useRef<HTMLButtonElement>(null);
  const addGroupButtonRef = useRef<HTMLButtonElement>(null);

  function updateItem(id: string, next: RuleListItemValues) {
    onChange(items.map((item) => (item.id === id ? next : item)));
  }

  // 지우기 전에 포커스를 이웃 그룹의 머리 줄로 옮긴다. 이웃이 단일 규칙이면 머리 줄이 없어(그 키의 토글이 없다) 추가
  // 버튼으로 간다 — 그룹을 받는 목록이면 언제나 누를 수 있는 '규칙 그룹 추가'로.
  function removeItem(id: string) {
    const index = items.findIndex((item) => item.id === id);
    const keys = items.map((item) => itemOpenKey(RULE_GROUP_LIST, item.id));
    focusNeighborToggle(keys, index, addGroupButtonRef.current ?? addRuleButtonRef.current);
    onChange(removeRuleListItem(items, id));
  }

  // 새 그룹은 펼친 채 만든다(안에 규칙을 바로 넣을 수 있게).
  function addGroup() {
    const id = crypto.randomUUID();
    uiState.open([itemOpenKey(RULE_GROUP_LIST, id)]);
    onChange([...items, { kind: "group", id, rules: [], nextOp: null }]);
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
                      groupOrdinal={items.slice(0, index + 1).filter((other) => other.kind === "group").length}
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
          ref={addRuleButtonRef}
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
          <Button ref={addGroupButtonRef} type="button" variant="secondary" size="sm" onClick={addGroup}>
            규칙 그룹 추가
          </Button>
        )}
      </div>
    </div>
  );
}

type EndingRowProps = {
  id: string;
  startingSetupIndex: number;
  endingIndex: number;
  stats: StatDefValues[];
  onRemove: () => void;
};

/** 엔딩 하나(이름/엔딩조건/판단 프롬프트 필수, 에필로그/엔딩힌트 선택 + 스탯 기반 규칙). 머리 줄은 손잡이·이름(읽기 전용
 * 제목)·요약·삭제 버튼이고 본문은 접힌다. */
function EndingRow({
  id,
  startingSetupIndex,
  endingIndex,
  stats,
  onRemove,
}: EndingRowProps) {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    register,
    control,
    setValue,
    formState: { errors },
  } = form;
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id });
  const endingPath = `startingSetups.${startingSetupIndex}.endings.${endingIndex}` as const;
  // 머리 줄 열림 키·제목·요약 재료.
  const endingId = useWatch({ control, name: `${endingPath}.id` });
  const name = useWatch({ control, name: `${endingPath}.name` });
  const turnGate = useWatch({ control, name: `${endingPath}.turnGate` });
  const statRules = useWatch({ control, name: `${endingPath}.statRules` });
  const endingErrors = errors.startingSetups?.[startingSetupIndex]?.endings?.[endingIndex];
  const epiloguePath = `${endingPath}.epilogue` as const;
  const epilogueField = register(epiloguePath);
  // "이미지 넣기"가 커서 자리를 읽을 입력창. `register` 의 ref 와 함께 건다.
  const epilogueRef = useRef<HTMLTextAreaElement | null>(null);
  const trimmedName = name.trim();
  // 그룹 안의 조건도 하나씩 센다 — 작가가 보는 "조건" 수다.
  const ruleCount = statRules.reduce((sum, item) => sum + (item.kind === "group" ? item.rules.length : 1), 0);
  const summary = [Number.isFinite(turnGate) ? `${turnGate}턴 이후` : undefined, `규칙 ${ruleCount}개`]
    .filter((part) => part !== undefined)
    .join(" · ");

  return (
    <CollapsibleItemCard
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      openKey={itemOpenKey(ENDING_LIST, endingId)}
      title={name}
      placeholderTitle="새 엔딩"
      srTitlePrefix={`${endingIndex + 1}번째 엔딩: `}
      summary={summary}
      hasError={!!endingErrors}
      leading={<ItemDragHandle {...attributes} {...listeners} aria-label={`${endingIndex + 1}번째 엔딩 순서 변경`} />}
      trailing={
        <ItemRemoveButton
          label={trimmedName ? `${trimmedName} 엔딩 삭제` : `${endingIndex + 1}번째 엔딩 삭제`}
          onClick={onRemove}
        />
      }
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`ending-${id}-name`}>이름 *</Label>
        <Input
          id={`ending-${id}-name`}
          placeholder="엔딩 이름을 입력해주세요"
          aria-invalid={!!endingErrors?.name}
          aria-describedby={endingErrors?.name ? `ending-${id}-name-error` : undefined}
          {...register(`${endingPath}.name`)}
        />
        {endingErrors?.name && (
          <p id={`ending-${id}-name-error`} role="alert" className="text-xs text-destructive-text">
            {endingErrors.name.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`ending-${id}-turn-gate`}>엔딩조건 (최소 턴수) *</Label>
        <Input
          id={`ending-${id}-turn-gate`}
          type="number"
          min={10}
          aria-invalid={!!endingErrors?.turnGate}
          aria-describedby={endingErrors?.turnGate ? `ending-${id}-turn-gate-error` : undefined}
          {...register(`${endingPath}.turnGate`, {
            valueAsNumber: true,
          })}
        />
        <p className="text-xs text-muted-foreground">최소 10턴 이상 진행돼야 이 엔딩을 판정해요.</p>
        {endingErrors?.turnGate && (
          <p id={`ending-${id}-turn-gate-error`} role="alert" className="text-xs text-destructive-text">
            {endingErrors.turnGate.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`ending-${id}-judge-prompt`}>판단 프롬프트 *</Label>
        <Textarea
          id={`ending-${id}-judge-prompt`}
          placeholder="이 엔딩에 도달했는지 AI가 판단할 기준을 입력해주세요"
          rows={3}
          aria-invalid={!!endingErrors?.judgePrompt}
          aria-describedby={endingErrors?.judgePrompt ? `ending-${id}-judge-prompt-error` : undefined}
          {...register(`${endingPath}.judgePrompt`)}
        />
        <MediaTagOutsideNotice name={`${endingPath}.judgePrompt`} />
        {endingErrors?.judgePrompt && (
          <p id={`ending-${id}-judge-prompt-error`} role="alert" className="text-xs text-destructive-text">
            {endingErrors.judgePrompt.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor={`ending-${id}-epilogue`}>에필로그</Label>
          <MediaTagInsertButton name={epiloguePath} fieldLabel="에필로그" textareaRef={epilogueRef} />
        </div>
        <Textarea
          id={`ending-${id}-epilogue`}
          placeholder="엔딩 도달 시 보여줄 에필로그를 입력해주세요"
          rows={3}
          aria-invalid={!!endingErrors?.epilogue}
          aria-describedby={endingErrors?.epilogue ? `ending-${id}-epilogue-error` : undefined}
          {...epilogueField}
          ref={(element) => {
            epilogueField.ref(element);
            epilogueRef.current = element;
          }}
        />
        <UnknownMediaTagNotice name={epiloguePath} />
        {endingErrors?.epilogue && (
          <p id={`ending-${id}-epilogue-error`} role="alert" className="text-xs text-destructive-text">
            {endingErrors.epilogue.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`ending-${id}-hint`}>엔딩힌트</Label>
        <Input
          id={`ending-${id}-hint`}
          placeholder="엔딩 힌트를 입력해주세요"
          aria-invalid={!!endingErrors?.hint}
          aria-describedby={endingErrors?.hint ? `ending-${id}-hint-error` : undefined}
          {...register(`${endingPath}.hint`)}
        />
        <MediaTagOutsideNotice name={`${endingPath}.hint`} />
        {endingErrors?.hint && (
          <p id={`ending-${id}-hint-error`} role="alert" className="text-xs text-destructive-text">
            {endingErrors.hint.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2 rounded-xl border border-border px-4 py-3">
        <span className="text-sm leading-none font-medium">스탯 기반 규칙 (선택)</span>
        <RuleListEditor
          items={statRules}
          stats={stats}
          allowGroups
          onChange={(next) =>
            setValue(`${endingPath}.statRules`, next, {
              shouldDirty: true,
            })
          }
        />
      </div>
    </CollapsibleItemCard>
  );
}

/** 선택된 시작설정 하나의 엔딩 목록. `key={시작설정 id}`로 감싸 StatSection과 동일하게 시작설정
 * 전환마다 useFieldArray를 완전히 새로 마운트한다. */
function EndingSection({ startingSetupIndex }: { startingSetupIndex: number }) {
  const form = useFormContext<StoryBuilderFormValues>();
  const uiState = useBuilderUiState();

  const { control, getValues } = form;
  const endingsPath = `startingSetups.${startingSetupIndex}.endings` as const;
  const { fields, append, remove, move } = useFieldArray({ control, name: endingsPath });
  const stats = useWatch({ control, name: `startingSetups.${startingSetupIndex}.stats` });
  const sensors = useSensors(useSensor(PointerSensor));
  const addButtonRef = useRef<HTMLButtonElement>(null);

  function handleDragEnd({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return;
    const oldIndex = fields.findIndex((field) => field.id === active.id);
    const newIndex = fields.findIndex((field) => field.id === over.id);
    if (oldIndex !== -1 && newIndex !== -1) move(oldIndex, newIndex);
  }

  // 지우기 전에 포커스를 다음 엔딩의 머리 줄로(없으면 이전 엔딩, 그것도 없으면 엔딩 추가 버튼으로) 옮긴다 — 지운 뒤로
  // 미루면 누른 삭제 버튼이 사라지며 포커스가 body 로 떨어진다.
  function handleRemove(index: number) {
    const keys = getValues(endingsPath).map((ending) => itemOpenKey(ENDING_LIST, ending.id));
    focusNeighborToggle(keys, index, addButtonRef.current);
    remove(index);
  }

  // 새 엔딩은 펼친 채 이름 칸에 포커스한다. 열림 기록은 `append` 와 같은 핸들러에서 먼저 해야 새 본문이 보이는 채로
  // 커밋된다. 포커스 칸을 이름으로 못 박는 이유: 지정하지 않으면 RHF 는 그 항목에서 먼저 등록된 칸으로 보내는데, 엔딩은
  // "이미지 넣기"용 ref 때문에 에필로그가 먼저 등록된다.
  function handleAdd() {
    const id = crypto.randomUUID();
    uiState.open([itemOpenKey(ENDING_LIST, id)]);
    append(
      {
        id,
        name: "",
        turnGate: 10,
        judgePrompt: "",
        statRules: [],
        epilogue: "",
        hint: "",
      },
      { focusName: `${endingsPath}.${fields.length}.name` },
    );
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
                  startingSetupIndex={startingSetupIndex}
                  endingIndex={index}
                  stats={stats}
                  onRemove={() => handleRemove(index)}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      <Button ref={addButtonRef} type="button" variant="secondary" className="w-fit" onClick={handleAdd}>
        엔딩 추가
      </Button>
    </div>
  );
}
