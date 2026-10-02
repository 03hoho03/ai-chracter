import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useRef } from "react";
import { Controller, useFieldArray, useFormContext, useWatch } from "react-hook-form";

import { STAT_ICON_OPTIONS } from "@/entities/chat-room";
import {
  CollapsibleItemCard,
  focusNeighborToggle,
  ItemRemoveButton,
  itemOpenKey,
  useBuilderSelection,
  useBuilderUiState,
} from "@/features/build-common";
import {
  planStatRemoval,
  SELECTED_STARTING_SETUP,
  type StatDefValues,
  type StoryBuilderFormValues,
  type StoryCollapsibleList,
} from "@/features/build-story";
import { MediaBookConfirmModal } from "@/features/edit-media-book";
import { ColorPicker, IconPicker } from "@/shared/ui/color-icon-picker";

import { MediaTagOutsideNotice } from "./MediaTagOutsideNotice";

/** 열림 키의 목록 이름 — 발행 실패 때 셸이 오류 항목을 여는 키와 같은 이름이어야 한다(타입이 목록 정의의 키로 묶는다). */
const STAT_LIST: StoryCollapsibleList = "stat";

/** 탭 전체가 선택사항(0개도 발행 가능), 스탯은 시작설정별로
 * 독립이라 이 탭은 먼저 시작설정을 고른 뒤 그 시작설정의 스탯만 편집한다. 고른 시작설정은 셸의 화면 상태에 둔다 — 탭을
 * 옮겨도 남고 엔딩 탭과 같은 값을 보며, 발행 실패 때 셸이 오류가 있는 시작설정으로 바꿔 놓을 수 있다. */
export function StatTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const { control } = form;
  const startingSetups = useWatch({ control, name: "startingSetups" });
  const [selectedSetupId, setSelectedSetupId] = useBuilderSelection(SELECTED_STARTING_SETUP);

  if (startingSetups.length === 0) {
    // 다른 탭 본문과 같은 `py-6` 루트로 감싸야 탭 목록과의 간격이 탭마다 같다.
    return (
      <div className="py-6">
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-20 text-center">
          <p className="text-sm text-muted-foreground">먼저 시작설정 탭에서 시작설정을 추가해주세요.</p>
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
 * add/remove만 지원한다(IntroTab의 예시 대화와 동일한 판단).
 *
 * 머리 줄은 이름(읽기 전용 제목)·요약·삭제 버튼이고 본문은 접힌다. 본문 줄은 모두 카드 안쪽 좌우 끝을 함께 쓴다 — 삭제
 * 버튼이 머리 줄에 있어 이름 칸이 다른 줄보다 짧아지지 않고, 수치 네 칸과 턴당 변화 칸이 같은 열 격자를 쓴다. */
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
  const statPath = `startingSetups.${startingSetupIndex}.stats.${statIndex}` as const;
  // 머리 줄 제목·요약 재료. 이 스탯만 구독해 다른 스탯을 고칠 때는 다시 그리지 않는다.
  const stat = useWatch({ control, name: statPath });
  const statErrors = errors.startingSetups?.[startingSetupIndex]?.stats?.[statIndex];
  const trimmedName = stat.name.trim();
  const errorIds = {
    icon: `stat-${id}-icon-error`,
    color: `stat-${id}-color-error`,
    name: `stat-${id}-name-error`,
  };

  return (
    <CollapsibleItemCard
      openKey={itemOpenKey(STAT_LIST, stat.id)}
      title={stat.name}
      placeholderTitle="새 스탯"
      srTitlePrefix={`${statIndex + 1}번째 스탯: `}
      summary={<StatSummary stat={stat} />}
      hasError={!!statErrors}
      trailing={
        <ItemRemoveButton
          label={trimmedName ? `${trimmedName} 스탯 삭제` : `${statIndex + 1}번째 스탯 삭제`}
          onClick={onRemove}
        />
      }
    >
      {/* 라벨은 이름 칸 위에만 둔다. 아이콘·색 버튼은 각자 이름("아이콘 선택 *")을 갖고, 라벨이 세 컨트롤 위에 걸치지
          않아야 버튼과 입력칸이 같은 윗선·같은 높이(36px)에 선다. */}
      <div className="grid grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-x-2 gap-y-1.5">
        <Label htmlFor={`stat-${id}-name`} className="col-start-3">
          이름 *
        </Label>
        <Controller
          control={control}
          name={`${statPath}.icon`}
          render={({ field }) => (
            <div data-field-path={`${statPath}.icon`}>
              <IconPicker
                value={field.value}
                onChange={field.onChange}
                options={STAT_ICON_OPTIONS}
                triggerLabel="아이콘 선택 *"
                aria-invalid={!!statErrors?.icon}
                aria-describedby={statErrors?.icon ? errorIds.icon : undefined}
              />
            </div>
          )}
        />
        <Controller
          control={control}
          name={`${statPath}.color`}
          render={({ field }) => (
            <div data-field-path={`${statPath}.color`}>
              <ColorPicker
                value={field.value}
                onChange={field.onChange}
                triggerLabel="색상 선택 *"
                aria-invalid={!!statErrors?.color}
                aria-describedby={statErrors?.color ? errorIds.color : undefined}
              />
            </div>
          )}
        />
        <Input
          id={`stat-${id}-name`}
          placeholder="스탯 이름을 입력해주세요"
          aria-invalid={!!statErrors?.name}
          aria-describedby={statErrors?.name ? errorIds.name : undefined}
          {...register(`${statPath}.name`)}
        />
        {/* 세 오류 문장은 줄 아래 전폭에 모은다 — 36px 버튼 열 아래에 두면 한두 글자씩 줄이 바뀐다. */}
        {statErrors?.icon && (
          <p id={errorIds.icon} role="alert" className="col-span-full text-xs text-destructive-text">
            {statErrors.icon.message}
          </p>
        )}
        {statErrors?.color && (
          <p id={errorIds.color} role="alert" className="col-span-full text-xs text-destructive-text">
            {statErrors.color.message}
          </p>
        )}
        {statErrors?.name && (
          <p id={errorIds.name} role="alert" className="col-span-full text-xs text-destructive-text">
            {statErrors.name.message}
          </p>
        )}
      </div>

      {/* 수치 네 칸은 넓으면 한 줄, 좁으면 2×2. 아래 턴당 변화 줄도 같은 열 격자를 써 열 경계가 맞는다. 오류 문장이 한
          칸만 키워도 이웃 칸의 윗선이 그대로이게 위로 붙인다. */}
      <div className="grid grid-cols-2 items-start gap-3 sm:grid-cols-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-min`}>최소값 *</Label>
          <Input
            id={`stat-${id}-min`}
            type="number"
            aria-invalid={!!statErrors?.min}
            aria-describedby={statErrors?.min ? `stat-${id}-min-error` : undefined}
            {...register(`${statPath}.min`, { valueAsNumber: true })}
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
            {...register(`${statPath}.max`, { valueAsNumber: true })}
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
            {...register(`${statPath}.initial`, { valueAsNumber: true })}
          />
          {statErrors?.initial && (
            <p id={`stat-${id}-initial-error`} role="alert" className="text-xs text-destructive-text">
              {statErrors.initial.message}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-unit`}>단위</Label>
          <Input
            id={`stat-${id}-unit`}
            placeholder="예: pt, %"
            aria-invalid={!!statErrors?.unit}
            aria-describedby={statErrors?.unit ? `stat-${id}-unit-error` : undefined}
            {...register(`${statPath}.unit`)}
          />
          {statErrors?.unit && (
            <p id={`stat-${id}-unit-error`} role="alert" className="text-xs text-destructive-text">
              {statErrors.unit.message}
            </p>
          )}
        </div>
      </div>

      {/* 입력칸은 위 격자의 첫 칸 폭이고, 힌트는 넓으면 그 옆 나머지 세 열에, 좁으면(2열) 다음 줄 전폭에 선다 — 좁은 칸
          옆에 두면 힌트가 다섯 줄로 접힌다. */}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`stat-${id}-per-turn-delta`}>턴당 자동 변화</Label>
        <div className="grid grid-cols-2 items-start gap-x-3 gap-y-1.5 sm:grid-cols-4">
          <div className="flex flex-col gap-1.5">
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
              {...register(`${statPath}.perTurnDelta`, {
                setValueAs: (value) => (value === "" || value === null ? undefined : Number(value)),
              })}
            />
            {statErrors?.perTurnDelta && (
              <p id={`stat-${id}-per-turn-delta-error`} role="alert" className="text-xs text-destructive-text">
                {statErrors.perTurnDelta.message}
              </p>
            )}
          </div>
          <p
            id={`stat-${id}-per-turn-delta-hint`}
            className="col-span-2 text-xs break-keep text-muted-foreground sm:col-span-3 sm:flex sm:min-h-9 sm:items-center"
          >
            매 턴 이만큼 자동으로 변해요(줄어들면 -1처럼 음수). 비워두면 AI가 대화를 보고 판단해요.
          </p>
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
          {...register(`${statPath}.description`)}
        />
        <MediaTagOutsideNotice name={`${statPath}.description`} />
        {statErrors?.description && (
          <p id={`stat-${id}-description-error`} role="alert" className="text-xs text-destructive-text">
            {statErrors.description.message}
          </p>
        )}
      </div>
    </CollapsibleItemCard>
  );
}

/** 접힌 머리 줄에서 스탯을 가를 최소 정보 — 고른 아이콘·색, 범위와 초기값, 턴당 변화. 비었거나 숫자가 아닌 칸은
 * 빼고(빈 구분자를 남기지 않는다), 아이콘·색 표식은 장식이라 읽지 않는다. */
function StatSummary({ stat }: { stat: StatDefValues }) {
  const StatIcon = STAT_ICON_OPTIONS.find((option) => option.name === stat.icon)?.Icon;
  const { min, max, initial, perTurnDelta } = stat;
  const parts = [
    Number.isFinite(min) && Number.isFinite(max) ? `${min}~${max}` : undefined,
    Number.isFinite(initial) ? `초기 ${initial}` : undefined,
    perTurnDelta !== undefined && Number.isFinite(perTurnDelta)
      ? `턴당 ${perTurnDelta > 0 ? "+" : ""}${perTurnDelta}`
      : undefined,
  ].filter((part) => part !== undefined);

  return (
    <>
      {StatIcon && <StatIcon aria-hidden className="mr-1 inline-block size-3.5" />}
      {stat.color && (
        <span
          aria-hidden
          className="mr-1.5 inline-block size-2.5 rounded-full align-middle"
          style={{ backgroundColor: stat.color }}
        />
      )}
      {parts.join(" · ")}
    </>
  );
}

/** 선택된 시작설정 하나의 스탯 목록. `key={시작설정 id}`로 감싸 시작설정을 전환할 때마다
 * useFieldArray가 새 index로 완전히 새로 마운트되게 한다(name의 인덱스만 바뀌는 걸 이 훅이
 * 안정적으로 재구독하지 않아서, 상위 StatTab이 이 컴포넌트 자체를 remount하는 방식으로 우회). */
function StatSection({ startingSetupIndex }: { startingSetupIndex: number }) {
  const form = useFormContext<StoryBuilderFormValues>();
  const uiState = useBuilderUiState();

  const { control, getValues, setValue } = form;
  const statsPath = `startingSetups.${startingSetupIndex}.stats` as const;
  const { fields, append, remove } = useFieldArray({ control, name: statsPath });

  const addButtonRef = useRef<HTMLButtonElement>(null);

  // 지운 스탯 자리에서 포커스를 다음 스탯의 머리 줄로(없으면 이전 스탯, 그것도 없으면 스탯 추가 버튼으로) 옮긴다. `keys` 는
  // 지우기 전 목록이다 — 이웃 스탯의 머리 줄은 지운 뒤에도 그대로 남는다.
  function focusAfterRemoval(keys: readonly string[], statIndex: number) {
    focusNeighborToggle(keys, statIndex, addButtonRef.current);
  }

  // 스탯은 시작설정마다 독립이라 이 시작설정의 엔딩만 본다. 그 스탯을 쓰는 엔딩 조건이 있으면 먼저 묻고,
  // 확인하면 그 조건을 지운 뒤 스탯을 지운다. 취소하면 아무것도 바꾸지 않는다.
  async function handleRemove(statIndex: number) {
    const keys = getValues(statsPath).map((stat) => itemOpenKey(STAT_LIST, stat.id));
    const removedStatId = getValues(`${statsPath}.${statIndex}.id`);
    const trigger = document.activeElement;
    let isAsked = false;
    const updates = await planStatRemoval(
      getValues(`startingSetups.${startingSetupIndex}.endings`),
      removedStatId,
      (ruleCount) => {
        isAsked = true;
        return MediaBookConfirmModal.call({
          title: "스탯을 지울까요?",
          description: `이 스탯을 쓰는 엔딩 조건 ${ruleCount}개도 함께 지워져요.`,
          confirmLabel: "지우기",
          // 취소면 삭제 버튼으로, 지웠으면 그 카드가 사라지므로 이웃 스탯의 머리 줄(없으면 스탯 추가 버튼)로.
          onRestoreFocus: () => {
            if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
            else focusAfterRemoval(keys, statIndex);
          },
        });
      },
    );
    if (updates === undefined) return;
    // 묻지 않고 지우는 경로는 지우기 전에 옮긴다 — 지운 뒤로 미루면 누른 삭제 버튼이 사라지며 포커스가 body 로 떨어진다.
    if (!isAsked) focusAfterRemoval(keys, statIndex);
    for (const { endingIndex, statRules } of updates) {
      setValue(`startingSetups.${startingSetupIndex}.endings.${endingIndex}.statRules`, statRules, {
        shouldDirty: true,
      });
    }
    remove(statIndex);
  }

  // 새 스탯은 펼친 채 이름 칸에 포커스한다. 열림 기록을 `append` 와 같은 핸들러에서 먼저 해야 새 본문이 처음부터 보이는
  // 채로 커밋되고, 그 뒤 `append` 가 주는 포커스가 숨은 칸에 헛걸리지 않는다. 포커스 칸은 이름으로 못 박는다 — 등록 순서에
  // 맡기면 아이콘·색 피커가 ref 를 받게 바뀌는 순간 포커스가 그쪽으로 간다.
  function handleAdd() {
    const id = crypto.randomUUID();
    uiState.open([itemOpenKey(STAT_LIST, id)]);
    append(
      {
        id,
        name: "",
        icon: "",
        color: "",
        min: 0,
        max: 100,
        initial: 0,
        unit: "",
        description: "",
      },
      { focusName: `${statsPath}.${fields.length}.name` },
    );
  }

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
            onRemove={() => void handleRemove(statIndex)}
          />
        ))
      )}

      <Button ref={addButtonRef} type="button" variant="secondary" className="w-fit" onClick={handleAdd}>
        스탯 추가
      </Button>
    </div>
  );
}
