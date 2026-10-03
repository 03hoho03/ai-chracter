import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useFormContext } from "react-hook-form";

import {
  FieldLabelText,
  STAT_CHANGE_CONFLICT_MESSAGE,
  STAT_CHANGE_DIRECTION_LABELS,
  STAT_CHANGE_DIRECTIONS,
  type StatChangeDirection,
  type StatDefValues,
  type StoryBuilderFormValues,
} from "@/features/build-story";

import { perTurnDeltaFromInput } from "../model/perTurnDelta";
import {
  isBlockedMaxChangeKey,
  isBlockedMaxChangePaste,
  maxChangePerTurnFromInput,
  statChangeMode,
  type StatChangeMode,
} from "../model/statChange";

/** 칸 아래 한 문장 — 지금 어느 쪽이 쓰이고 있어 무엇이 잠겼는지, 다른 쪽으로 가려면 무엇을 비우는지 말한다. */
const STAT_CHANGE_HINT: Record<StatChangeMode, string> = {
  free: "매 턴 이만큼 자동으로 변해요(줄어들면 -1처럼 음수). 비워 두면 AI가 대화를 보고 판단하고, 그때는 AI가 바꿀 수 있는 방향과 한 턴 최대 폭을 정할 수 있어요.",
  perTurn: "턴당 자동 변화가 있으면 AI가 이 스탯을 바꾸지 않아서 변화 방향과 한 턴 최대 폭은 쓰지 않아요.",
  limit:
    "AI가 정한 값이 이 방향과 폭을 넘으면 시스템이 잘라요. 매 턴 같은 만큼 자동으로 바꾸려면 변화 방향을 오르내림으로, 최대 폭을 비워 주세요.",
  conflict: STAT_CHANGE_CONFLICT_MESSAGE,
};

function isStatChangeDirection(value: string): value is StatChangeDirection {
  return STAT_CHANGE_DIRECTIONS.some((direction) => direction === value);
}

type StatChangeFieldsProps = {
  /** 칸 id 접두어(스탯 행의 안정 id). */
  id: string;
  startingSetupIndex: number;
  statIndex: number;
  stat: StatDefValues;
};

/**
 * 스탯 값이 바뀌는 방식 — 턴당 자동 변화 · 변화 방향 · 한 턴 최대 폭. 위 수치 네 칸과 같은 열 격자를 써 열 경계가 맞는다.
 * 좁으면(2열) 턴당 자동 변화가 첫 줄에 혼자, 방향·폭이 둘째 줄에 짝으로 서서 "둘 중 하나"라는 관계가 배치로도 보인다.
 *
 * 둘은 함께 쓸 수 없어 먼저 채운 쪽이 다른 쪽을 잠근다(`statChangeMode`). 잠금은 사유를 늘 아래 문장에 두고
 * `aria-describedby` 로 잇는다 — 잠긴 칸이 포커스 순서에서 빠져도 이유는 화면과 앞 칸에서 읽힌다. 잠가도 값은 지우지 않는다.
 */
export function StatChangeFields({ id, startingSetupIndex, statIndex, stat }: StatChangeFieldsProps) {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    register,
    setValue,
    formState: { errors },
  } = form;
  const statPath = `startingSetups.${startingSetupIndex}.stats.${statIndex}` as const;
  const statErrors = errors.startingSetups?.[startingSetupIndex]?.stats?.[statIndex];
  const mode = statChangeMode(stat);
  const isLimitLocked = mode === "perTurn";
  const isPerTurnLocked = mode === "limit";
  const ids = {
    perTurn: `stat-${id}-per-turn-delta`,
    perTurnError: `stat-${id}-per-turn-delta-error`,
    direction: `stat-${id}-change-direction`,
    maxChange: `stat-${id}-max-change`,
    maxChangeError: `stat-${id}-max-change-error`,
    hint: `stat-${id}-change-hint`,
  };
  // 둘을 함께 건 스탯의 폼 오류는 턴당 칸에 붙지만 같은 문장이 아래 힌트 자리에 이미 있다 — 칸 아래에 한 번 더 쓰지 않는다.
  const perTurnError =
    statErrors?.perTurnDelta?.message === STAT_CHANGE_CONFLICT_MESSAGE ? undefined : statErrors?.perTurnDelta;
  const describedBy = (errorId: string | undefined) => [ids.hint, errorId].filter(Boolean).join(" ");

  return (
    <div className="flex flex-col gap-1.5">
      <div className="grid grid-cols-2 items-start gap-3 sm:grid-cols-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={ids.perTurn}><FieldLabelText field="startingSetups.*.stats.*.perTurnDelta" /></Label>
          <Input
            id={ids.perTurn}
            type="number"
            step={1}
            placeholder="예: -1"
            disabled={isPerTurnLocked}
            aria-invalid={!!statErrors?.perTurnDelta}
            aria-describedby={describedBy(perTurnError ? ids.perTurnError : undefined)}
            {...register(`${statPath}.perTurnDelta`, { setValueAs: perTurnDeltaFromInput })}
          />
          {perTurnError && (
            <p id={ids.perTurnError} role="alert" className="text-xs break-keep text-destructive-text">
              {perTurnError.message}
            </p>
          )}
        </div>

        {/* 좁은 2열에서는 첫 칸 다음 자리를 비우고 다음 줄로 내린다. */}
        <div className="col-start-1 flex flex-col gap-1.5 sm:col-start-2">
          <Label htmlFor={ids.direction}><FieldLabelText field="startingSetups.*.stats.*.changeDirection" /></Label>
          <Select
            value={stat.changeDirection}
            disabled={isLimitLocked}
            onValueChange={(value) => {
              if (isStatChangeDirection(value)) setValue(`${statPath}.changeDirection`, value, { shouldDirty: true });
            }}
          >
            <SelectTrigger id={ids.direction} className="w-full" aria-describedby={ids.hint}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STAT_CHANGE_DIRECTIONS.map((direction) => (
                <SelectItem key={direction} value={direction}>
                  {STAT_CHANGE_DIRECTION_LABELS[direction]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor={ids.maxChange}><FieldLabelText field="startingSetups.*.stats.*.maxChangePerTurn" /></Label>
          {/* 음수·소수·지수 글자는 키로도 붙여 넣기로도 받지 않는다 — 정수가 아닌 값은 서버가 초안 저장째 거절해 그 뒤
              자동저장이 멈춘다. 그래도 들어온 값은 입력 변환이 걸러 폼 검증 오류로 남긴다. */}
          <Input
            id={ids.maxChange}
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            placeholder="제한 없음"
            disabled={isLimitLocked}
            aria-invalid={!!statErrors?.maxChangePerTurn}
            aria-describedby={describedBy(statErrors?.maxChangePerTurn ? ids.maxChangeError : undefined)}
            onKeyDown={(event) => {
              if (isBlockedMaxChangeKey(event.key)) event.preventDefault();
            }}
            onPaste={(event) => {
              if (isBlockedMaxChangePaste(event.clipboardData.getData("text"))) event.preventDefault();
            }}
            {...register(`${statPath}.maxChangePerTurn`, { setValueAs: maxChangePerTurnFromInput })}
          />
          {statErrors?.maxChangePerTurn && (
            <p id={ids.maxChangeError} role="alert" className="text-xs break-keep text-destructive-text">
              {statErrors.maxChangePerTurn.message}
            </p>
          )}
        </div>
      </div>

      <p
        id={ids.hint}
        className={cn("text-xs break-keep", mode === "conflict" ? "text-destructive-text" : "text-muted-foreground")}
      >
        {STAT_CHANGE_HINT[mode]}
      </p>
    </div>
  );
}
