import { closestCenter, DndContext } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { useId, useRef, useState, type Ref } from "react";
import { Controller, useFieldArray, useFormContext } from "react-hook-form";

import {
  FieldCharacterCount,
  ItemDragHandle,
  ItemRemoveButton,
  sortableHandleId,
  useLimitedTextField,
  useSortableList,
  type SortableHandleProps,
} from "@/features/build-common";
import {
  FieldLabelText,
  MAX_STAT_RULE_CONDITION_LENGTH,
  MAX_STAT_RULES,
  STAT_RULE_LIMIT_MESSAGE,
  type StatDefValues,
  type StoryBuilderFormValues,
} from "@/features/build-story";
import { BuilderTextarea } from "@/shared/ui/BuilderTextarea";

import {
  formatStatRuleDelta,
  statChangeMode,
  statRuleDeltaFromInput,
  statRuleDeltaHint,
} from "../model/statChange";

/** 턴당 자동 변화가 있어 추가를 잠갔을 때의 사유. 이 상태에서는 목록이 비어 있다(둘 다 있으면 충돌 상태라 잠그지 않는다). */
const COUNTER_LOCK_REASON = "턴당 자동 변화가 있는 스탯은 AI가 판정하지 않아 규칙을 쓰지 않아요. 규칙을 쓰려면 턴당 자동 변화를 비워 주세요.";

type StatRuleListProps = {
  /** 칸 id 접두어(스탯 행의 안정 id). */
  id: string;
  startingSetupIndex: number;
  statIndex: number;
  /** 지금 스탯 값 — 스탯 행이 이미 구독하고 있어 목록이 같은 값을 따로 구독하지 않는다. */
  stat: StatDefValues;
};

/**
 * 스탯의 「조건 → 증감」 규칙 목록. 판정 AI 는 이번 턴에 맞은 규칙만 고르고, 코드가 그중 폭의 절댓값이 가장 큰 하나(같으면 목록
 * 앞)를 더한다 — 그래서 순서가 동점의 우선순위라 손잡이로 끌거나 화살표 키로 재정렬한다. 빈 목록도 저장되지만, 턴당 자동 변화가
 * 없는 스탯이면 발행 검증이 목록 자리에 오류를 붙인다(규칙 없는 판정 스탯은 변하지 않는다).
 *
 * 상한(`MAX_STAT_RULES`)이나 턴당 자동 변화 잠금에서는 추가 버튼을 지우지 않고 `aria-disabled` 로 잠근 채 사유를 잇는다 —
 * `disabled` 는 누른 버튼의 포커스를 body 로 떨어뜨린다. 자동저장은 폼 검증을 거치지 않아 상한을 넘은 목록이 폼에 들어가면 서버가
 * 초안 저장을 통째로 거절하므로, 실제 차단은 클릭 핸들러가 한다.
 */
export function StatRuleList({ id, startingSetupIndex, statIndex, stat }: StatRuleListProps) {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    control,
    formState: { errors },
  } = form;
  const statPath = `startingSetups.${startingSetupIndex}.stats.${statIndex}` as const;
  const rulesPath = `${statPath}.rules` as const;
  const { fields, append, remove, move } = useFieldArray({ control, name: rulesPath });
  const sortable = useSortableList({
    ids: fields.map((field) => field.id),
    move,
    itemObject: "규칙을",
    orderMeaning: "폭이 같으면 위에 있는 규칙이 적용돼요.",
  });
  const addButtonRef = useRef<HTMLButtonElement>(null);
  const rulesErrors = errors.startingSetups?.[startingSetupIndex]?.stats?.[statIndex]?.rules;
  // 목록 자체에 걸린 오류(개수 상한·판정 스탯의 규칙 없음). 배열 자리 오류는 `.message` 와 `.root.message` 로 갈릴 수 있어
  // 둘 다 읽는다.
  const listError = rulesErrors?.message ?? rulesErrors?.root?.message;
  const isFull = fields.length >= MAX_STAT_RULES;
  const isCounterLocked = statChangeMode(stat) === "perTurn";
  let lockReason: string | undefined;
  if (isFull) lockReason = STAT_RULE_LIMIT_MESSAGE;
  else if (isCounterLocked) lockReason = COUNTER_LOCK_REASON;
  const ids = {
    label: `stat-${id}-rules-label`,
    count: `stat-${id}-rules-count`,
    guide: `stat-${id}-rules-guide`,
    error: `stat-${id}-rules-error`,
    reason: `stat-${id}-rules-reason`,
  };
  function handleAdd() {
    if (lockReason !== undefined) return;
    // 증감은 빈 칸(NaN)으로 둔다 — 부호를 작가가 직접 고르게 한다. 다 채우기 전까지 자동저장은 이 규칙만 빼고 보낸다.
    append({ id: crypto.randomUUID(), condition: "", delta: Number.NaN }, { focusName: `${rulesPath}.${fields.length}.condition` });
  }

  // 지운 자리의 다음 규칙(없으면 앞 규칙, 그것도 없으면 추가 버튼)의 손잡이로 포커스를 옮긴다 — 삭제 버튼이 사라지며 포커스가
  // body 로 떨어지지 않게 지우기 전에 옮긴다.
  function handleRemove(index: number) {
    const neighborId = fields[index + 1]?.id ?? fields[index - 1]?.id;
    const neighbor = neighborId === undefined ? null : document.getElementById(sortableHandleId(neighborId));
    (neighbor ?? addButtonRef.current)?.focus();
    remove(index);
    sortable.announce("규칙을 지웠어요.");
  }

  return (
    <div className="flex flex-col gap-2" role="group" aria-labelledby={ids.label} aria-describedby={ids.guide}>
      <div className="flex items-baseline justify-between gap-2">
        <span id={ids.label} className="text-sm leading-none font-medium">
          <FieldLabelText field="startingSetups.*.stats.*.rules" />
        </span>
        <span id={ids.count} className="text-xs tabular-nums text-muted-foreground">
          규칙 {fields.length} / {MAX_STAT_RULES}
        </span>
      </div>
      <p id={ids.guide} className="text-xs break-keep text-muted-foreground">
        AI가 이번 턴의 사용자 메시지와 응답만 보고 맞는 규칙을 골라요. 여럿이 맞아도 폭이 가장 큰 하나만 더해지고, 폭이 같으면
        위의 규칙이에요. 조건은 이번 턴에 사용자가 한 행동으로 적고, 평범한 턴에는 아무 규칙도 맞지 않게 써 주세요.
      </p>

      {fields.length === 0 ? (
        <p className="text-sm break-keep text-muted-foreground">
          {/* 턴당 자동 변화가 있는 스탯은 규칙을 쓰지 않으므로 빈 목록이 정상이다 — 그때는 잠금 사유가 아래에 따로 보인다. */}
          {isCounterLocked ? "아직 규칙이 없어요." : "아직 규칙이 없어요. 규칙이 없으면 이 스탯은 변하지 않고, 발행할 수 없어요."}
        </p>
      ) : (
        <DndContext
          sensors={sortable.sensors}
          collisionDetection={closestCenter}
          onDragEnd={sortable.handleDragEnd}
          accessibility={sortable.accessibility}
        >
          <SortableContext items={fields.map((field) => field.id)} strategy={verticalListSortingStrategy}>
            <ol className="flex flex-col gap-2" aria-label="규칙 목록(폭이 같으면 위의 규칙이 적용돼요)">
              {fields.map((field, index) => (
                <StatRuleRow
                  key={field.id}
                  sortableId={field.id}
                  rulePath={`${rulesPath}.${index}`}
                  position={index + 1}
                  range={stat}
                  onRemove={() => handleRemove(index)}
                  handleProps={sortable.handleProps(index)}
                />
              ))}
            </ol>
          </SortableContext>
        </DndContext>
      )}

      {!!listError && (
        <p id={ids.error} role="alert" className="text-xs break-keep text-destructive-text">
          {listError}
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <Button
          ref={addButtonRef}
          type="button"
          variant="secondary"
          size="sm"
          className="w-fit aria-disabled:pointer-events-none aria-disabled:opacity-65"
          aria-disabled={lockReason !== undefined || undefined}
          aria-describedby={lockReason === undefined ? undefined : ids.reason}
          // 발행 실패가 목록 자리(개수 상한·규칙 없음)를 가리키면 셸이 이 버튼을 찾아 포커스한다.
          data-field-path={rulesPath}
          onClick={handleAdd}
        >
          규칙 추가
        </Button>
        {lockReason !== undefined && (
          <p id={ids.reason} className="text-xs break-keep text-muted-foreground">
            {lockReason}
          </p>
        )}
      </div>

      <p className="sr-only" aria-live="polite">
        {sortable.announcement}
      </p>
    </div>
  );
}

type StatRuleRowProps = {
  /** dnd-kit 정렬 id(RHF 렌더 키). */
  sortableId: string;
  rulePath: `startingSetups.${number}.stats.${number}.rules.${number}`;
  position: number;
  /** 폭 경고에 쓰는 스탯 범위. */
  range: { min: number; max: number };
  onRemove: () => void;
  /** 손잡이의 id·화살표 키 재정렬(`useSortableList`). */
  handleProps: SortableHandleProps;
};

/**
 * 규칙 한 줄 — [손잡이] [조건 · 증감] [삭제]. 조건과 증감은 줄 폭이 넉넉하면 나란히(조건이 남는 폭을 쓴다), 좁으면 위아래로
 * 선다. 같은 줄이 넓은 화면의 카드와 좁은 화면 양쪽에 들어가 폭이 뷰포트만으로 정해지지 않아 컨테이너 폭으로 가른다.
 *
 * 조건 칸은 등록한 입력이라 입력할 때 상한(코드 포인트)에서 자른다. 서버는 앞뒤 공백을 지운 뒤 세므로 화면이 같거나 더
 * 엄격하다.
 */
function StatRuleRow({ sortableId, rulePath, position, range, onRemove, handleProps }: StatRuleRowProps) {
  const form = useFormContext<StoryBuilderFormValues>();
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: sortableId });

  const { control, getFieldState, formState } = form;
  const conditionField = useLimitedTextField<StoryBuilderFormValues>(`${rulePath}.condition`, MAX_STAT_RULE_CONDITION_LENGTH);
  const conditionError = getFieldState(`${rulePath}.condition`, formState).error;
  const generatedId = useId();
  const ids = {
    condition: `${generatedId}-condition`,
    conditionCount: `${generatedId}-condition-count`,
    conditionError: `${generatedId}-condition-error`,
    delta: `${generatedId}-delta`,
    deltaNote: `${generatedId}-delta-note`,
  };

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="flex items-start gap-2 rounded-lg border border-border bg-background p-3"
    >
      <ItemDragHandle
        {...attributes}
        {...listeners}
        {...handleProps}
        aria-label={`${position}번째 규칙 순서 변경`}
      />

      <div className="@container min-w-0 flex-1">
        <div className="grid gap-3 @md:grid-cols-stat-rule">
          <div className="flex min-w-0 flex-col gap-1.5">
            <Label htmlFor={ids.condition}>
              <FieldLabelText field="startingSetups.*.stats.*.rules.*.condition" />
            </Label>
            <BuilderTextarea
              id={ids.condition}
              placeholder="예: 사용자가 약속한 시간에 늦었다"
              rows={2}
              aria-invalid={!!conditionError}
              aria-describedby={[ids.conditionCount, conditionError ? ids.conditionError : undefined]
                .filter(Boolean)
                .join(" ")}
              {...conditionField.registration}
            />
            <FieldCharacterCount
              id={ids.conditionCount}
              name={conditionField.registration.name}
              max={MAX_STAT_RULE_CONDITION_LENGTH}
              isTruncated={conditionField.isTruncated}
            />
            {conditionError && (
              <p id={ids.conditionError} role="alert" className="text-xs break-keep text-destructive-text">
                {conditionError.message}
              </p>
            )}
          </div>

          <Controller
            control={control}
            name={`${rulePath}.delta`}
            render={({ field, fieldState }) => (
              <StatRuleDeltaField
                id={ids.delta}
                noteId={ids.deltaNote}
                inputRef={field.ref}
                name={field.name}
                value={field.value}
                onChange={field.onChange}
                onBlur={field.onBlur}
                range={range}
                errorMessage={fieldState.error?.message}
              />
            )}
          />
        </div>
      </div>

      <ItemRemoveButton label={`${position}번째 규칙 삭제`} onClick={onRemove} />
    </li>
  );
}

type StatRuleDeltaFieldProps = {
  id: string;
  noteId: string;
  inputRef: Ref<HTMLInputElement>;
  name: string;
  value: number;
  onChange: (value: number) => void;
  onBlur: () => void;
  range: { min: number; max: number };
  /** 발행 검증이 붙인 오류. 있으면 입력 중 안내 대신 이것을 보인다. */
  errorMessage: string | undefined;
};

/**
 * 증감 칸과 그 아래 한 줄. 부호를 숫자 앞에 직접 적는 글 입력이다 — `type="number"` 는 `+3` 을 값으로 읽지 못하고, 숫자 자판에는
 * 빼기 부호가 없는 기기가 있다. 입력한 글은 그대로 두고(쓰다 만 `-` 가 지워지지 않게) 폼 값만 읽은 숫자로 바꾸며, 칸을 떠날 때
 * 읽힌 값이면 `+3`·`-5` 모양으로 맞춘다. 폼 값이 바깥에서 바뀌면(되돌리기 등으로 다시 채워질 때) 글도 그 값으로 다시 맞춘다 —
 * 지금 글이 같은 값을 뜻하면 손대지 않는다.
 *
 * 아래 한 줄은 발행 오류가 있으면 그 오류(`role="alert"`), 없으면 저장을 막지 않는 입력 중 안내(읽지 못한 글·0·범위 폭 초과)다.
 * 칸 열(6rem)에 두면 한두 글자씩 줄이 바뀌어 부모 격자의 전폭 줄로 낸다 — 그래서 칸과 문장을 조각으로 돌려준다.
 */
function StatRuleDeltaField({
  id,
  noteId,
  inputRef,
  name,
  value,
  onChange,
  onBlur,
  range,
  errorMessage,
}: StatRuleDeltaFieldProps) {
  const [text, setText] = useState(() => formatStatRuleDelta(value));
  const [syncedValue, setSyncedValue] = useState(value);
  if (!Object.is(syncedValue, value)) {
    setSyncedValue(value);
    if (!Object.is(statRuleDeltaFromInput(text), value)) setText(formatStatRuleDelta(value));
  }
  const hint = errorMessage === undefined ? statRuleDeltaHint(text, value, range) : undefined;
  const note = errorMessage ?? hint;

  return (
    <>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={id}>
          <FieldLabelText field="startingSetups.*.stats.*.rules.*.delta" />
        </Label>
        <Input
          ref={inputRef}
          id={id}
          name={name}
          type="text"
          autoComplete="off"
          placeholder="예: +3"
          maxLength={8}
          className="w-28 @md:w-full"
          value={text}
          aria-invalid={errorMessage !== undefined}
          aria-describedby={note === undefined ? undefined : noteId}
          onChange={(event) => {
            setText(event.target.value);
            onChange(statRuleDeltaFromInput(event.target.value));
          }}
          onBlur={() => {
            if (Number.isFinite(value)) setText(formatStatRuleDelta(value));
            onBlur();
          }}
        />
      </div>
      {errorMessage !== undefined && (
        <p id={noteId} role="alert" className="text-xs -mt-1.5 break-keep text-destructive-text @md:col-span-2">
          {errorMessage}
        </p>
      )}
      {hint !== undefined && (
        <p id={noteId} className="text-xs -mt-1.5 break-keep text-muted-foreground @md:col-span-2">
          {hint}
        </p>
      )}
    </>
  );
}
