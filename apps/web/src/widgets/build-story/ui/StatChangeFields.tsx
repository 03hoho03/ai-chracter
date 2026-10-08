import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { useFormContext } from "react-hook-form";

import { FieldLabelText, type StatDefValues, type StoryBuilderFormValues } from "@/features/build-story";

import { perTurnDeltaFromInput } from "../model/perTurnDelta";
import { statChangeMode, type StatChangeMode } from "../model/statChange";

/** 칸 아래 한 문장 — 지금 어느 쪽이 쓰이고 있어 무엇이 잠겼는지, 다른 쪽으로 가려면 무엇을 비우는지 말한다. 둘 다 채워진
 * 상태도 안내일 뿐 오류 톤이 아니다 — 발행을 막는 오류 문장은 폼 검증이 턴당 칸에 붙여 그 칸 아래에만 보인다. */
const STAT_CHANGE_HINT: Record<StatChangeMode, string> = {
  free: "매 턴 이만큼 자동으로 변해요(줄어들면 -1처럼 음수). 대화에 따라 오르내리는 스탯이면 비워 두고 아래 규칙을 적어 주세요.",
  perTurn: "턴당 자동 변화가 있으면 AI가 이 스탯을 판정하지 않아서 규칙은 쓰지 않아요.",
  rules: "규칙이 있으면 턴당 자동 변화는 쓰지 않아요. 매 턴 같은 만큼 자동으로 바꾸려면 아래 규칙을 모두 지워 주세요.",
  conflict: "턴당 자동 변화와 규칙은 함께 쓸 수 없어요. 하나를 비워 주세요.",
};

type StatChangeFieldsProps = {
  /** 칸 id 접두어(스탯 행의 안정 id). */
  id: string;
  startingSetupIndex: number;
  statIndex: number;
  stat: StatDefValues;
};

/**
 * 턴당 자동 변화 칸. 위 수치 네 칸과 같은 열 격자의 첫 칸을 써 열 경계가 맞는다.
 *
 * 규칙과는 함께 쓸 수 없어 먼저 채운 쪽이 다른 쪽을 잠근다(`statChangeMode`) — 규칙이 하나라도 있으면 이 칸이 잠기고, 이 칸이
 * 차 있으면 규칙 목록의 추가 버튼이 잠긴다. 잠금은 사유를 늘 아래 문장에 두고 `aria-describedby` 로 잇는다 — 잠긴 칸이 포커스
 * 순서에서 빠져도 이유는 화면에서 읽힌다. 잠가도 값은 지우지 않는다.
 */
export function StatChangeFields({ id, startingSetupIndex, statIndex, stat }: StatChangeFieldsProps) {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    register,
    formState: { errors },
  } = form;
  const statPath = `startingSetups.${startingSetupIndex}.stats.${statIndex}` as const;
  const statErrors = errors.startingSetups?.[startingSetupIndex]?.stats?.[statIndex];
  const mode = statChangeMode(stat);
  const ids = {
    perTurn: `stat-${id}-per-turn-delta`,
    perTurnError: `stat-${id}-per-turn-delta-error`,
    hint: `stat-${id}-change-hint`,
  };

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
            disabled={mode === "rules"}
            aria-invalid={!!statErrors?.perTurnDelta}
            aria-describedby={[ids.hint, statErrors?.perTurnDelta ? ids.perTurnError : undefined].filter(Boolean).join(" ")}
            {...register(`${statPath}.perTurnDelta`, { setValueAs: perTurnDeltaFromInput })}
          />
        </div>
      </div>

      {statErrors?.perTurnDelta && (
        <p id={ids.perTurnError} role="alert" className="text-xs break-keep text-destructive-text">
          {statErrors.perTurnDelta.message}
        </p>
      )}
      <p id={ids.hint} className="text-xs break-keep text-muted-foreground">
        {STAT_CHANGE_HINT[mode]}
      </p>
    </div>
  );
}
