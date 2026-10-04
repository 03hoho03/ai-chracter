import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useEffect, useRef, type RefObject } from "react";
import { flushSync } from "react-dom";
import { Controller, useFieldArray, useFormContext, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { STAT_ICON_OPTIONS } from "@/entities/chat-room";
import {
  CollapsibleItemCard,
  focusItemToggle,
  focusNeighborToggle,
  ItemRemoveButton,
  itemOpenKey,
  revealItemToggle,
  useBuilderSelection,
  useBuilderUiState,
} from "@/features/build-common";
import {
  FieldLabelText,
  hasPerTurnDelta,
  planStatRemoval,
  SELECTED_STARTING_SETUP,
  StatSummary,
  STORY_FIELD_LABELS,
  type StoryBuilderFormValues,
  type StoryCollapsibleList,
} from "@/features/build-story";
import { MediaBookConfirmModal } from "@/features/edit-media-book";
import { ColorPicker, IconPicker } from "@/shared/ui/color-icon-picker";

import { MediaTagOutsideNotice } from "./MediaTagOutsideNotice";
import { StartingSetupPicker } from "./StartingSetupPicker";
import { StatChangeFields } from "./StatChangeFields";
import { StoryMacroNotice } from "./StoryMacroNotice";
import { UNDO_TOAST_DURATION_MS, UndoToastButton } from "./UndoToastButton";
import { moveStatErrorsById } from "../model/moveStatErrorsById";
import { orderWithPendingRemovals, restoreRemovedStat, type RemovedStat } from "../model/restoreRemovedStat";
import { revalidateStatRange, revalidateStatRangeIfInvalid } from "../model/statRangeValidation";
import { statRemovalConfirmDescription } from "../model/statRemovalConfirm";

/** 열림 키의 목록 이름 — 발행 실패 때 셸이 오류 항목을 여는 키와 같은 이름이어야 한다(타입이 목록 정의의 키로 묶는다). */
const STAT_LIST: StoryCollapsibleList = "stat";

/** 아직 되돌릴 수 있는 스탯 삭제 — 토스트 id 별로, 지운 차례대로. 삭제마다 토스트를 따로 띄워 연달아 지워도 앞의 삭제를
 * 되돌릴 길이 남는다. 토스트가 닫히면(시간이 다 됐거나 되돌렸거나) 빠진다. */
type PendingStatRemovals = Map<string, RemovedStat>;

/** 탭 전체가 선택사항(0개도 발행 가능), 스탯은 시작설정별로
 * 독립이라 이 탭은 먼저 시작설정을 고른 뒤 그 시작설정의 스탯만 편집한다. 고른 시작설정은 셸의 화면 상태에 둔다 — 탭을
 * 옮겨도 남고 엔딩 탭과 같은 값을 보며, 발행 실패 때 셸이 오류가 있는 시작설정으로 바꿔 놓을 수 있다. */
export function StatTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const { control } = form;
  const startingSetups = useWatch({ control, name: "startingSetups" });
  const [selectedSetupId, setSelectedSetupId] = useBuilderSelection(SELECTED_STARTING_SETUP);
  // 시작설정을 바꾸면 스탯 목록이 다시 마운트되므로 탭이 쥔다 — 바꾼 뒤에도 앞서 지운 스탯을 되돌릴 수 있다.
  const pendingRemovalsRef = useRef<PendingStatRemovals>(new Map());

  // 스탯 삭제의 되돌리기는 이 탭이 보이는 동안만 둔다 — 다른 탭에서 누르면 무엇이 돌아왔는지 보이지 않고, 빌더를 떠난
  // 뒤에 누르면 자동저장이 없는 폼에 써서 조용히 사라진다.
  useEffect(() => {
    const pendingRemovals = pendingRemovalsRef.current;
    return () => {
      for (const toastId of pendingRemovals.keys()) toast.dismiss(toastId);
      pendingRemovals.clear();
    };
  }, []);

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
        itemNoun="스탯"
        note="스탯이 하나도 없어도 발행할 수 있어요."
      />

      {effectiveSetup && (
        <StatSection
          key={effectiveSetup.id}
          startingSetupIndex={effectiveIndex}
          pendingRemovalsRef={pendingRemovalsRef}
        />
      )}
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
  // 범위 세 칸은 칸을 떠날 때 이 스탯만 검사해 모순을 발행 전에 알리고, 오류가 떠 있으면 고치는 입력마다 다시 검사해 바로
  // 풀어 준다. 폼 전체의 검증 시점(발행 전엔 조용히)과 자동저장은 그대로다.
  const rangeFieldOptions = {
    valueAsNumber: true,
    onBlur: () => void revalidateStatRange(form, statPath),
    onChange: () => void revalidateStatRangeIfInvalid(form, statPath),
  } as const;
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
      {/* 라벨은 이름 칸 위에만 둔다. 아이콘·색 버튼은 각자 지금 값을 말하는 이름("아이콘: 피로, 바꾸기")을 갖고, 라벨이
          세 컨트롤 위에 걸치지 않아야 마우스 화면에서 버튼과 입력칸이 같은 윗선·같은 높이(36px)에 선다. 터치 화면에서는 버튼만
          40px 로 커져 입력칸(36px)보다 크고, 줄이 가운데 정렬이라 위아래로 2px 씩 비어져 나온다. */}
      <div className="grid grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-x-2 gap-y-1.5">
        <Label htmlFor={`stat-${id}-name`} className="col-start-3">
          <FieldLabelText field="startingSetups.*.stats.*.name" />
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
                label={STORY_FIELD_LABELS["startingSetups.*.stats.*.icon"].label}
                isRequired
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
                label={STORY_FIELD_LABELS["startingSetups.*.stats.*.color"].label}
                isRequired
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
          <p id={errorIds.icon} role="alert" className="col-span-full text-xs break-keep text-destructive-text">
            {statErrors.icon.message}
          </p>
        )}
        {statErrors?.color && (
          <p id={errorIds.color} role="alert" className="col-span-full text-xs break-keep text-destructive-text">
            {statErrors.color.message}
          </p>
        )}
        {statErrors?.name && (
          <p id={errorIds.name} role="alert" className="col-span-full text-xs break-keep text-destructive-text">
            {statErrors.name.message}
          </p>
        )}
      </div>

      {/* 수치 네 칸은 넓으면 한 줄, 좁으면 2×2. 아래 턴당 변화 줄도 같은 열 격자를 써 열 경계가 맞는다. 오류 문장이 한
          칸만 키워도 이웃 칸의 윗선이 그대로이게 위로 붙인다. */}
      <div className="grid grid-cols-2 items-start gap-3 sm:grid-cols-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-min`}><FieldLabelText field="startingSetups.*.stats.*.min" /></Label>
          <Input
            id={`stat-${id}-min`}
            type="number"
            step={1}
            aria-invalid={!!statErrors?.min}
            aria-describedby={statErrors?.min ? `stat-${id}-min-error` : undefined}
            {...register(`${statPath}.min`, rangeFieldOptions)}
          />
          {statErrors?.min && (
            <p id={`stat-${id}-min-error`} role="alert" className="text-xs break-keep text-destructive-text">
              {statErrors.min.message}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-max`}><FieldLabelText field="startingSetups.*.stats.*.max" /></Label>
          <Input
            id={`stat-${id}-max`}
            type="number"
            step={1}
            aria-invalid={!!statErrors?.max}
            aria-describedby={statErrors?.max ? `stat-${id}-max-error` : undefined}
            {...register(`${statPath}.max`, rangeFieldOptions)}
          />
          {statErrors?.max && (
            <p id={`stat-${id}-max-error`} role="alert" className="text-xs break-keep text-destructive-text">
              {statErrors.max.message}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-initial`}><FieldLabelText field="startingSetups.*.stats.*.initial" /></Label>
          <Input
            id={`stat-${id}-initial`}
            type="number"
            step={1}
            aria-invalid={!!statErrors?.initial}
            aria-describedby={statErrors?.initial ? `stat-${id}-initial-error` : undefined}
            {...register(`${statPath}.initial`, rangeFieldOptions)}
          />
          {statErrors?.initial && (
            <p id={`stat-${id}-initial-error`} role="alert" className="text-xs break-keep text-destructive-text">
              {statErrors.initial.message}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`stat-${id}-unit`}><FieldLabelText field="startingSetups.*.stats.*.unit" /></Label>
          <Input
            id={`stat-${id}-unit`}
            placeholder="예: pt, %"
            aria-invalid={!!statErrors?.unit}
            aria-describedby={statErrors?.unit ? `stat-${id}-unit-error` : undefined}
            {...register(`${statPath}.unit`)}
          />
          {statErrors?.unit && (
            <p id={`stat-${id}-unit-error`} role="alert" className="text-xs break-keep text-destructive-text">
              {statErrors.unit.message}
            </p>
          )}
        </div>
      </div>

      <StatChangeFields id={id} startingSetupIndex={startingSetupIndex} statIndex={statIndex} stat={stat} />

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`stat-${id}-description`}><FieldLabelText field="startingSetups.*.stats.*.description" /></Label>
        <Textarea
          id={`stat-${id}-description`}
          placeholder="스탯에 대한 설명을 입력해주세요"
          rows={2}
          aria-invalid={!!statErrors?.description}
          aria-describedby={[
            `stat-${id}-description-hint`,
            statErrors?.description ? `stat-${id}-description-error` : undefined,
          ]
            .filter(Boolean)
            .join(" ")}
          {...register(`${statPath}.description`)}
        />
        {/* 판정 AI 는 매 턴 이 설명과 이번 턴 대화만 보고 값을 정한다. 턴당 변화가 있는 스탯은 시스템이 그 값만큼 굴리고
            AI 가 낸 판단은 버린다 — 그때 "올리고 내리는 기준"을 써 달라고 하면 효과 없는 일을 시키는 셈이라 문장을 바꾼다. */}
        <p id={`stat-${id}-description-hint`} className="text-xs break-keep text-muted-foreground">
          {hasPerTurnDelta(stat)
            ? "턴당 자동 변화가 있어서 AI는 이 스탯을 바꾸지 않고, 매 턴 정해진 만큼만 변해요. 이 스탯이 이야기에서 무엇을 뜻하는지 적어 주세요."
            : "AI가 매 턴 이 설명을 읽고 값을 바꿔요. 무엇이 올리고 무엇이 내리는지, 한 번에 얼마나 움직이는지 적어 주세요."}
        </p>
        <MediaTagOutsideNotice name={`${statPath}.description`} />
        <StoryMacroNotice name={`${statPath}.description`} />
        {statErrors?.description && (
          <p id={`stat-${id}-description-error`} role="alert" className="text-xs break-keep text-destructive-text">
            {statErrors.description.message}
          </p>
        )}
      </div>
    </CollapsibleItemCard>
  );
}

/** 토스트 문장의 목적어("‘도희 호감도’ 스탯", 이름이 비었으면 "이름 없는 스탯"). */
function statNoun(removed: RemovedStat): string {
  const name = removed.stat.name.trim();
  return name ? `‘${name}’ 스탯` : "이름 없는 스탯";
}

/**
 * 되살린 스탯의 머리 줄로 포커스를 옮기고 그 머리 줄이 보이게 한다. 되돌리기 버튼에 포커스가 있으면 첫 이동이 토스트를
 * 떠나는 순간 sonner 가 토스트에 들어오기 전 자리로 포커스를 돌려보내고 그 자리를 잊는다 — 그래서 한 번 더 옮긴다.
 * 버튼에 포커스가 없었으면(클릭이 포커스를 주지 않는 브라우저) 첫 이동으로 끝나고 둘째는 아무것도 바꾸지 않는다.
 *
 * 포커스는 스크롤 없이 주고, 보이게 하는 일은 다음 프레임에 따로 한다. 지금 보이는 스탯 위쪽에 카드를 끼워 넣으면 브라우저의
 * 스크롤 앵커링이 보이던 스탯을 제자리에 두려고 카드 높이만큼 스크롤을 내려, 되살린 머리 줄이 화면 위로 밀려난다(포커스의
 * `preventScroll` 은 이것을 막지 않는다). 그 조정 뒤에 머리 줄만 화면 안으로 들인다 — 이미 보이면 움직이지 않고, 부드러운
 * 스크롤을 쓰지 않아 움직임 줄이기 설정과 상관없이 한 번에 옮긴다.
 */
function focusRestoredToggle(openKey: string) {
  if (focusItemToggle(openKey, { preventScroll: true })) focusItemToggle(openKey, { preventScroll: true });
  requestAnimationFrame(() => revealItemToggle(openKey));
}

/** 선택된 시작설정 하나의 스탯 목록. `key={시작설정 id}`로 감싸 시작설정을 전환할 때마다
 * useFieldArray가 새 index로 완전히 새로 마운트되게 한다(name의 인덱스만 바뀌는 걸 이 훅이
 * 안정적으로 재구독하지 않아서, 상위 StatTab이 이 컴포넌트 자체를 remount하는 방식으로 우회). */
function StatSection({
  startingSetupIndex,
  pendingRemovalsRef,
}: {
  startingSetupIndex: number;
  pendingRemovalsRef: RefObject<PendingStatRemovals>;
}) {
  const form = useFormContext<StoryBuilderFormValues>();
  const uiState = useBuilderUiState();

  const { control, getValues, setValue, setError, clearErrors, formState } = form;
  const statsPath = `startingSetups.${startingSetupIndex}.stats` as const;
  const { fields, append, remove } = useFieldArray({ control, name: statsPath });

  const addButtonRef = useRef<HTMLButtonElement>(null);

  // 지운 스탯 자리에서 포커스를 다음 스탯의 머리 줄로(없으면 이전 스탯, 그것도 없으면 스탯 추가 버튼으로) 옮긴다. `keys` 는
  // 지우기 전 목록이다 — 이웃 스탯의 머리 줄은 지운 뒤에도 그대로 남는다.
  function focusAfterRemoval(keys: readonly string[], statIndex: number) {
    focusNeighborToggle(keys, statIndex, addButtonRef.current);
  }

  // 스탯은 시작설정마다 독립이라 이 시작설정의 엔딩·상황 노트만 본다. 그 스탯을 쓰는 조건이 있으면 둘을 함께 세어 한 번만
  // 묻고, 확인하면 그 조건을 지운 뒤 스탯을 지운다. 취소하면 아무것도 바꾸지 않는다.
  async function handleRemove(statIndex: number) {
    const keys = getValues(statsPath).map((stat) => itemOpenKey(STAT_LIST, stat.id));
    const removedStatId = getValues(`${statsPath}.${statIndex}.id`);
    const trigger = document.activeElement;
    let isAsked = false;
    const updates = await planStatRemoval(
      getValues(`startingSetups.${startingSetupIndex}`),
      removedStatId,
      (counts) => {
        isAsked = true;
        return MediaBookConfirmModal.call({
          title: "스탯을 지울까요?",
          description: statRemovalConfirmDescription(counts),
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
    for (const { endingIndex, statRules } of updates.endings) {
      setValue(`startingSetups.${startingSetupIndex}.endings.${endingIndex}.statRules`, statRules, {
        shouldDirty: true,
      });
    }
    for (const { noteIndex, conditionRules } of updates.situationNotes) {
      setValue(`startingSetups.${startingSetupIndex}.situationNotes.${noteIndex}.conditionRules`, conditionRules, {
        shouldDirty: true,
      });
    }
    const startingSetupId = getValues(`startingSetups.${startingSetupIndex}.id`);
    const removed: RemovedStat = {
      startingSetupId,
      order: orderWithPendingRemovals(
        getValues(statsPath).map((stat) => stat.id),
        [...pendingRemovalsRef.current.values()].filter((each) => each.startingSetupId === startingSetupId),
      ),
      stat: structuredClone(getValues(`${statsPath}.${statIndex}`)),
    };
    remove(statIndex);
    // 되돌리기는 묻지 않고 지운 경로에만 둔다. 확인을 거친 삭제는 엔딩·상황 노트 조건도 함께 지웠고 사용자가 그것까지
    // 보고 확정했다 — 되돌리려면 조건을 원래 자리(그룹 안 포함)에 다시 끼워야 하는데, 그 사이 고치면 자리가 어긋난다.
    if (!isAsked) offerUndo(removed);
  }

  /** 확인 없이 지우는 대신 방금 지운 스탯을 되살릴 길을 둔다 — 머리 줄의 삭제 버튼이 펼치기 버튼 바로 옆이라
   * 잘못 누르기 쉽고(지우면 아래 카드가 올라와 같은 자리에 다음 삭제 버튼이 선다), 지운 결과는 곧바로 자동저장된다.
   * 삭제마다 토스트를 따로 띄워 연달아 지운 것도 하나씩 되돌린다. */
  function offerUndo(removed: RemovedStat) {
    const toastId = `stat-remove-undo-${crypto.randomUUID()}`;
    const pendingRemovals = pendingRemovalsRef.current;
    pendingRemovals.set(toastId, removed);
    const forget = () => void pendingRemovals.delete(toastId);
    toast(`${statNoun(removed)}을 지웠어요.`, {
      id: toastId,
      duration: UNDO_TOAST_DURATION_MS,
      onDismiss: forget,
      onAutoClose: forget,
      action: (
        <UndoToastButton
          onClick={() => {
            forget();
            toast.dismiss(toastId);
            undoRemoval(removed);
          }}
        />
      ),
    });
  }

  // 이 섹션은 그 사이 다른 시작설정을 고르며 언마운트됐을 수 있다 — 필드 배열 대신 폼 값을 경로로 읽고 쓴다(폼과 화면
  // 상태 저장소는 셸이 쥐어 살아 있다).
  function undoRemoval(removed: RemovedStat) {
    const restored = restoreRemovedStat(getValues("startingSetups"), removed);
    if (restored === undefined) {
      toast("그 사이 목록이 바뀌어서 스탯을 되돌리지 않았어요.");
      return;
    }
    const restoredStatsPath = `startingSetups.${restored.startingSetupIndex}.stats` as const;
    const beforeIds = getValues(restoredStatsPath).map((stat) => stat.id);
    const afterIds = restored.stats.map((stat) => stat.id);
    const statErrors = formState.errors.startingSetups?.[restored.startingSetupIndex]?.stats;
    const movedErrors = moveStatErrorsById(beforeIds, (index) => statErrors?.[index], afterIds);
    // 되살린 스탯이 보이도록 그 시작설정을 고르고, 머리 줄이 생기도록 동기로 커밋한다. 열림 기록은 지울 때 지우지 않아
    // 같은 id 로 돌아오면 지우기 전 펼침 그대로다.
    flushSync(() => {
      uiState.select(SELECTED_STARTING_SETUP, removed.startingSetupId);
      setValue(restoredStatsPath, restored.stats, { shouldDirty: true });
      // `setValue` 는 오류를 옛 인덱스에 두므로 스탯 id 를 따라 다시 꽂는다. 되살린 스탯 자신은 오류 없이 돌아온다(다음
      // blur 나 발행 때 다시 검사된다). 오류만 바꾸므로 자동저장은 돌지 않는다.
      afterIds.forEach((_, index) => clearErrors(`${restoredStatsPath}.${index}`));
      for (const { statIndex, field, error } of movedErrors) {
        setError(`${restoredStatsPath}.${statIndex}.${field}`, error);
      }
    });
    focusRestoredToggle(itemOpenKey(STAT_LIST, removed.stat.id));
    toast.success(`${statNoun(removed)}을 되돌렸어요.`);
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
        perTurnDelta: null,
        changeDirection: "both",
        maxChangePerTurn: null,
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
