import { closestCenter, DndContext } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { TriangleAlert } from "lucide-react";
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
  useSortableList,
  useUndoableRemoval,
  type SortableHandleProps,
} from "@/features/build-common";
import {
  endingSummary,
  FieldLabelText,
  hasRuleWithMissingStat,
  isMissingStat,
  SELECTED_STARTING_SETUP,
  type StatDefValues,
  type StoryBuilderFormValues,
  type StoryCollapsibleList,
} from "@/features/build-story";

import { MediaTagInsertButton } from "./MediaTagInsertButton";
import { MediaTagOutsideNotice } from "./MediaTagOutsideNotice";
import { RuleListEditor } from "./RuleListEditor";
import { StartingSetupPicker } from "./StartingSetupPicker";
import { StoryMacroNotice } from "./StoryMacroNotice";
import { UnknownMediaTagNotice } from "./UnknownMediaTagNotice";

/** 열림 키의 목록 이름 — 발행 실패 때 셸이 오류 항목을 여는 키와 같은 이름이어야 한다(타입이 목록 정의의 키로 묶는다). */
const ENDING_LIST: StoryCollapsibleList = "ending";
const RULE_GROUP_LIST: StoryCollapsibleList = "ruleGroup";

/** 엔딩의 스탯 규칙은 선택이다 — 비워 두면 판단 프롬프트만으로 판정한다. */
const ENDING_RULES_EMPTY_TEXT = "등록된 규칙이 없어요. 비워두면 판단 프롬프트만으로 엔딩을 판정해요.";

/** 우선순위 스탯 '없음'의 선택지 값. Radix Select 는 빈 문자열을 값으로 받지 않아, 폼의 `null` 과 이 값을 오간다. 스탯 id 는
 * UUID 라 겹치지 않는다. */
const NO_PRIORITY_STAT = "none";

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

type EndingRowProps = {
  id: string;
  startingSetupIndex: number;
  endingIndex: number;
  stats: StatDefValues[];
  /** 손잡이의 id·화살표 키 재정렬(`useSortableList`). */
  handleProps: SortableHandleProps;
  onRemove: () => void;
};

/** 엔딩 하나(이름/엔딩조건/판단 프롬프트 필수, 에필로그/엔딩힌트 선택 + 스탯 기반 규칙). 머리 줄은 손잡이·이름(읽기 전용
 * 제목)·요약·삭제 버튼이고 본문은 접힌다. */
function EndingRow({
  id,
  startingSetupIndex,
  endingIndex,
  stats,
  handleProps,
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
  const priorityStatId = useWatch({ control, name: `${endingPath}.priorityStatId` });
  const isPriorityStatMissing = priorityStatId !== null && isMissingStat(priorityStatId, stats);
  const endingErrors = errors.startingSetups?.[startingSetupIndex]?.endings?.[endingIndex];
  const epiloguePath = `${endingPath}.epilogue` as const;
  const epilogueField = register(epiloguePath);
  // "이미지 넣기"가 커서 자리를 읽을 입력창. `register` 의 ref 와 함께 건다.
  const epilogueRef = useRef<HTMLTextAreaElement | null>(null);
  const trimmedName = name.trim();

  return (
    <CollapsibleItemCard
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      openKey={itemOpenKey(ENDING_LIST, endingId)}
      title={name}
      placeholderTitle="새 엔딩"
      srTitlePrefix={`${endingIndex + 1}번째 엔딩: `}
      summary={endingSummary({ turnGate, statRules })}
      // 지워진 스탯을 쓰는 조건은 폼 오류가 아니라 데이터 사실이라 따로 본다 — 접혀 있어도 머리 줄에 경고가 보여야 찾는다.
      hasError={!!endingErrors || hasRuleWithMissingStat(statRules, stats) || isPriorityStatMissing}
      leading={
        <ItemDragHandle
          {...attributes}
          {...listeners}
          {...handleProps}
          aria-label={`${endingIndex + 1}번째 엔딩 순서 변경`}
        />
      }
      trailing={
        <ItemRemoveButton
          label={trimmedName ? `${trimmedName} 엔딩 삭제` : `${endingIndex + 1}번째 엔딩 삭제`}
          onClick={onRemove}
        />
      }
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`ending-${id}-name`}><FieldLabelText field="startingSetups.*.endings.*.name" /></Label>
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
        <Label htmlFor={`ending-${id}-turn-gate`}><FieldLabelText field="startingSetups.*.endings.*.turnGate" /></Label>
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
        <Label htmlFor={`ending-${id}-judge-prompt`}><FieldLabelText field="startingSetups.*.endings.*.judgePrompt" /></Label>
        <Textarea
          id={`ending-${id}-judge-prompt`}
          placeholder="이 엔딩에 도달했는지 AI가 판단할 기준을 입력해주세요"
          rows={3}
          aria-invalid={!!endingErrors?.judgePrompt}
          aria-describedby={endingErrors?.judgePrompt ? `ending-${id}-judge-prompt-error` : undefined}
          {...register(`${endingPath}.judgePrompt`)}
        />
        <MediaTagOutsideNotice name={`${endingPath}.judgePrompt`} />
        <StoryMacroNotice name={`${endingPath}.judgePrompt`} />
        {endingErrors?.judgePrompt && (
          <p id={`ending-${id}-judge-prompt-error`} role="alert" className="text-xs text-destructive-text">
            {endingErrors.judgePrompt.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor={`ending-${id}-epilogue`}><FieldLabelText field="startingSetups.*.endings.*.epilogue" /></Label>
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
        <StoryMacroNotice name={epiloguePath} />
        {endingErrors?.epilogue && (
          <p id={`ending-${id}-epilogue-error`} role="alert" className="text-xs text-destructive-text">
            {endingErrors.epilogue.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`ending-${id}-hint`}><FieldLabelText field="startingSetups.*.endings.*.hint" /></Label>
        <Input
          id={`ending-${id}-hint`}
          placeholder="엔딩 힌트를 입력해주세요"
          aria-invalid={!!endingErrors?.hint}
          aria-describedby={endingErrors?.hint ? `ending-${id}-hint-error` : undefined}
          {...register(`${endingPath}.hint`)}
        />
        <MediaTagOutsideNotice name={`${endingPath}.hint`} />
        <StoryMacroNotice name={`${endingPath}.hint`} />
        {endingErrors?.hint && (
          <p id={`ending-${id}-hint-error`} role="alert" className="text-xs text-destructive-text">
            {endingErrors.hint.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2 rounded-xl border border-border px-4 py-3">
        <span className="text-sm leading-none font-medium"><FieldLabelText field="startingSetups.*.endings.*.statRules" /></span>
        <RuleListEditor
          items={statRules}
          stats={stats}
          allowGroups
          emptyText={ENDING_RULES_EMPTY_TEXT}
          groupList={RULE_GROUP_LIST}
          onChange={(next) =>
            setValue(`${endingPath}.statRules`, next, {
              shouldDirty: true,
            })
          }
        />
      </div>

      <PriorityStatField
        id={id}
        stats={stats}
        value={priorityStatId}
        isMissing={isPriorityStatMissing}
        onChange={(next) => setValue(`${endingPath}.priorityStatId`, next, { shouldDirty: true })}
      />
    </CollapsibleItemCard>
  );
}

type PriorityStatFieldProps = {
  id: string;
  stats: StatDefValues[];
  value: string | null;
  isMissing: boolean;
  onChange: (next: string | null) => void;
};

/**
 * 같은 턴에 조건을 넘은 엔딩이 여럿일 때 비교할 스탯. 고른 엔딩끼리는 각자 고른 스탯 값이 가장 높은 엔딩만(같으면 목록
 * 순서대로) 판정하고, 그 가운데 통과하는 엔딩이 없으면 그 턴엔 엔딩이 나지 않는다 — 그래서 설명은 비교 규칙과 그 결과를 함께
 * 말한다. 고른 스탯이 지워졌으면(다른 기기에서 고친 초안) 조건 줄과 같은 '지워짐' 표시와 고치는 법을 보인다. 서버는 그런
 * 초안의 저장을 거절한다.
 */
function PriorityStatField({ id, stats, value, isMissing, onChange }: PriorityStatFieldProps) {
  const triggerId = `ending-${id}-priority-stat`;
  const hintId = `${triggerId}-hint`;
  const missingHintId = `${triggerId}-missing`;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={triggerId}><FieldLabelText field="startingSetups.*.endings.*.priorityStatId" /></Label>
      <Select value={value ?? NO_PRIORITY_STAT} onValueChange={(next) => onChange(next === NO_PRIORITY_STAT ? null : next)}>
        <SelectTrigger
          id={triggerId}
          className="w-full sm:w-56"
          aria-invalid={isMissing || undefined}
          aria-describedby={isMissing ? `${missingHintId} ${hintId}` : hintId}
        >
          <SelectValue>
            {isMissing ? (
              <>
                <TriangleAlert aria-hidden className="size-3.5 text-destructive-text" />
                <span className="truncate text-destructive-text">지워짐</span>
              </>
            ) : undefined}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_PRIORITY_STAT}>없음</SelectItem>
          {stats.map((stat) => (
            <SelectItem key={stat.id} value={stat.id}>
              {stat.name || "이름없음"}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {isMissing && (
        <p id={missingHintId} className="text-xs break-keep text-destructive-text">
          고른 스탯이 지워졌어요. 다른 스탯을 고르거나 ‘없음’으로 바꿔 주세요.
        </p>
      )}
      <p id={hintId} className="text-xs break-keep text-muted-foreground">
        같은 턴에 여러 엔딩이 조건을 채우면, 우선순위 스탯을 고른 엔딩 가운데 그 값이 가장 높은 엔딩만 판정해요(같으면 목록
        위쪽부터). 가장 높은 엔딩이 하나도 판정을 통과하지 못하면 그 턴에는 엔딩이 나지 않아요.
      </p>
    </div>
  );
}

/** 선택된 시작설정 하나의 엔딩 목록. `key={시작설정 id}`로 감싸 StatSection과 동일하게 시작설정
 * 전환마다 useFieldArray를 완전히 새로 마운트한다. 삭제 되돌리기도 이 목록이 쥐어, 시작설정을 바꾸거나 탭을 떠나면 그 토스트가
 * 닫힌다 — 다시 마운트된 목록에는 지울 때 잡은 필드 배열이 없다. */
function EndingSection({ startingSetupIndex }: { startingSetupIndex: number }) {
  const form = useFormContext<StoryBuilderFormValues>();
  const uiState = useBuilderUiState();

  const { control, getValues } = form;
  const endingsPath = `startingSetups.${startingSetupIndex}.endings` as const;
  const { fields, append, remove, move, insert } = useFieldArray({ control, name: endingsPath });
  const stats = useWatch({ control, name: `startingSetups.${startingSetupIndex}.stats` });
  const sortable = useSortableList({
    ids: fields.map((field) => field.id),
    move,
    itemObject: "엔딩을",
    orderMeaning: "위에 있는 엔딩부터 판정해요.",
  });
  const removeWithUndo = useUndoableRemoval({
    getItems: () => getValues(endingsPath),
    remove,
    insert: (index, ending) => insert(index, ending, { shouldFocus: false }),
    openKey: (id) => itemOpenKey(ENDING_LIST, id),
    objectPhrase: (ending) => (ending.name.trim() ? `‘${ending.name.trim()}’ 엔딩을` : "이름 없는 엔딩을"),
  });
  const addButtonRef = useRef<HTMLButtonElement>(null);

  // 지우기 전에 포커스를 다음 엔딩의 머리 줄로(없으면 이전 엔딩, 그것도 없으면 엔딩 추가 버튼으로) 옮긴다 — 지운 뒤로
  // 미루면 누른 삭제 버튼이 사라지며 포커스가 body 로 떨어진다.
  function handleRemove(index: number) {
    const keys = getValues(endingsPath).map((ending) => itemOpenKey(ENDING_LIST, ending.id));
    focusNeighborToggle(keys, index, addButtonRef.current);
    removeWithUndo(index);
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
        priorityStatId: null,
      },
      { focusName: `${endingsPath}.${fields.length}.name` },
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm break-keep text-muted-foreground">
        같은 턴에 여러 엔딩 조건이 동시에 충족되면 목록 위쪽 엔딩부터 판정해요. 우선순위 스탯을 고른 엔딩끼리는 그 값이 가장
        높은 엔딩만 판정해요(같으면 목록 위쪽부터).
      </p>

      {fields.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-10 text-center">
          <p className="text-sm text-muted-foreground">아직 등록된 엔딩이 없어요.</p>
        </div>
      ) : (
        <DndContext
          sensors={sortable.sensors}
          collisionDetection={closestCenter}
          onDragEnd={sortable.handleDragEnd}
          accessibility={sortable.accessibility}
        >
          <SortableContext items={fields.map((field) => field.id)} strategy={verticalListSortingStrategy}>
            <div className="flex flex-col gap-4">
              {fields.map((field, index) => (
                <EndingRow
                  key={field.id}
                  id={field.id}
                  startingSetupIndex={startingSetupIndex}
                  endingIndex={index}
                  stats={stats}
                  handleProps={sortable.handleProps(index)}
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

      <p className="sr-only" aria-live="polite">
        {sortable.announcement}
      </p>
    </div>
  );
}
