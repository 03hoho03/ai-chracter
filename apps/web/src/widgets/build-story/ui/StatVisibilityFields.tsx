import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Switch } from "@ai-character-chat/ui/components/switch";
import { Controller, useFormContext } from "react-hook-form";

import { FieldCharacterCount, useLimitedTextField } from "@/features/build-common";
import {
  FieldLabelText,
  MAX_STAT_PLAYER_DESCRIPTION_LENGTH,
  type StatDefValues,
  type StoryBuilderFormValues,
} from "@/features/build-story";

type StatVisibilityFieldsProps = {
  /** 칸 id 접두어(스탯 행의 안정 id). */
  id: string;
  startingSetupIndex: number;
  statIndex: number;
  stat: StatDefValues;
};

/**
 * 플레이어 화면에서 이 스탯이 어떻게 보이는지 — 숨김, 플레이어용 설명, 숨긴 스탯의 익명 신호. 셋 다 AI 판정과 무관한 화면
 * 설정이다.
 *
 * 숨김이 켜지면 설명 칸이 잠기고(숨긴 스탯의 설명은 보일 곳이 없다), 꺼지면 신호 스위치가 잠긴다(신호는 숨긴 스탯에서만
 * 뜻이 있다). 턴당 자동 변화와 규칙의 상호 잠금(`StatChangeFields`)과 같은 꼴로, 잠금 사유는 늘 아래 문장에 두고
 * `aria-describedby` 로 잇고, 잠가도 값은 지우지 않는다 — 숨김을 껐다 켜도 쓴 설명과 고른 신호가 그대로 돌아온다.
 */
export function StatVisibilityFields({ id, startingSetupIndex, statIndex, stat }: StatVisibilityFieldsProps) {
  const {
    control,
    formState: { errors },
  } = useFormContext<StoryBuilderFormValues>();
  const statPath = `startingSetups.${startingSetupIndex}.stats.${statIndex}` as const;
  const descriptionField = useLimitedTextField<StoryBuilderFormValues>(
    `${statPath}.playerDescription`,
    MAX_STAT_PLAYER_DESCRIPTION_LENGTH,
  );
  const descriptionError = errors.startingSetups?.[startingSetupIndex]?.stats?.[statIndex]?.playerDescription;
  const isHidden = stat.hiddenFromPlayer;
  const ids = {
    hidden: `stat-${id}-hidden`,
    hiddenHint: `stat-${id}-hidden-hint`,
    description: `stat-${id}-player-description`,
    descriptionCount: `stat-${id}-player-description-count`,
    descriptionError: `stat-${id}-player-description-error`,
    signal: `stat-${id}-signal`,
    signalHint: `stat-${id}-signal-hint`,
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <Label htmlFor={ids.hidden}>
            <FieldLabelText field="startingSetups.*.stats.*.hiddenFromPlayer" />
          </Label>
          <p id={ids.hiddenHint} className="text-sm break-keep text-muted-foreground">
            켜면 플레이어 화면에 이 스탯이 보이지 않아요. AI는 그대로 판정하고 엔딩 조건에도 쓰여요.
          </p>
        </div>
        <Controller
          control={control}
          name={`${statPath}.hiddenFromPlayer`}
          render={({ field }) => (
            <Switch
              id={ids.hidden}
              checked={field.value}
              onCheckedChange={field.onChange}
              onBlur={field.onBlur}
              aria-describedby={ids.hiddenHint}
            />
          )}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={ids.description}>
          <FieldLabelText field="startingSetups.*.stats.*.playerDescription" />
        </Label>
        <Input
          id={ids.description}
          placeholder="예: 바닥나면 갱도를 걸어 나갈 수 없다"
          disabled={isHidden}
          aria-invalid={!!descriptionError}
          aria-describedby={[ids.descriptionCount, descriptionError ? ids.descriptionError : undefined]
            .filter(Boolean)
            .join(" ")}
          {...descriptionField.registration}
        />
        <FieldCharacterCount
          id={ids.descriptionCount}
          name={descriptionField.registration.name}
          max={MAX_STAT_PLAYER_DESCRIPTION_LENGTH}
          isTruncated={descriptionField.isTruncated}
          help={
            isHidden
              ? "숨긴 스탯이라 이 설명은 보이지 않아요. 숨김을 끄면 다시 보여요."
              : "플레이어가 게이지를 눌렀을 때 보여요. AI는 읽지 않아요."
          }
        />
        {descriptionError && (
          <p id={ids.descriptionError} role="alert" className="text-xs break-keep text-destructive-text">
            {descriptionError.message}
          </p>
        )}
      </div>

      <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <Label htmlFor={ids.signal}>
            <FieldLabelText field="startingSetups.*.stats.*.signalHiddenChange" />
          </Label>
          <p id={ids.signalHint} className="text-sm break-keep text-muted-foreground">
            {isHidden
              ? "이 스탯이 바뀐 턴에 플레이어 화면에 ‘무언가 달라졌다’만 보여요. 무엇이 얼마나 바뀌었는지는 보이지 않아요."
              : "숨긴 스탯에서만 써요. 위에서 숨김을 켜면 고를 수 있어요."}
          </p>
        </div>
        <Controller
          control={control}
          name={`${statPath}.signalHiddenChange`}
          render={({ field }) => (
            <Switch
              id={ids.signal}
              checked={field.value}
              onCheckedChange={field.onChange}
              onBlur={field.onBlur}
              disabled={!isHidden}
              aria-describedby={ids.signalHint}
            />
          )}
        />
      </div>
    </div>
  );
}
